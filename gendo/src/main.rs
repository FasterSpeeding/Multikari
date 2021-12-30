// BSD 3-Clause License
//
// Copyright (c) 2021, Lucina
// All rights reserved.
//
// Redistribution and use in source and binary forms, with or without
// modification, are permitted provided that the following conditions are met:
//
// * Redistributions of source code must retain the above copyright notice, this
//   list of conditions and the following disclaimer.
//
// * Redistributions in binary form must reproduce the above copyright notice,
//   this list of conditions and the following disclaimer in the documentation
//   and/or other materials provided with the distribution.
//
// * Neither the name of the copyright holder nor the names of its contributors
//   may be used to endorse or promote products derived from this software
//   without specific prior written permission.
//
// THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
// AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
// IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
// ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
// LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
// CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
// SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
// INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
// CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
// ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
// POSSIBILITY OF SUCH DAMAGE.
#![feature(async_closure)]
use std::io;
use std::str::FromStr;
use std::sync::Arc;

use actix_web::web::{Data, Path};
use actix_web::{get, patch, post, App, HttpRequest, HttpResponse, HttpServer};
use closure::closure;
use futures_util::StreamExt;
use openssl::ssl;
mod manager;
mod senders;
use senders::Sender;
use shared::dto;
use twilight_gateway::{Cluster, Intents};

fn shard_to_dto(shard: &twilight_gateway::Shard) -> dto::Shard {
    let is_alive;
    let latency;
    let session_id;
    let seq;
    if let Ok(info) = shard.info() {
        is_alive = true;
        latency = info.latency().recent().back().map(std::time::Duration::as_secs_f64);
        session_id = info.session_id().map(str::to_string);
        seq = Some(info.seq())
    } else {
        is_alive = false;
        latency = None;
        session_id = None;
        seq = None;
    };

    dto::Shard {
        heartbeat_latency: latency,
        is_alive,
        // intents: config.intents().bits(),
        session_id,
        seq,
        shard_id: shard.config().shard()[0],
    }
}

fn disconnect_to_dto(shard: &twilight_gateway::Shard, resume: twilight_gateway::shard::ResumeSession) -> dto::Shard {
    dto::Shard {
        heartbeat_latency: None,
        is_alive: true,
        // intents: config.intents().bits(),
        session_id: Some(resume.session_id),
        seq: Some(resume.sequence),
        shard_id: shard.config().shard()[0],
    }
}

#[post("/disconnect")]
async fn post_disconnect(cluster: Data<Arc<Cluster>>) -> HttpResponse {
    let results = cluster
        .down_resumable()
        .drain()
        .map(|(shard_id, resume)| disconnect_to_dto(cluster.shard(shard_id).unwrap(), resume))
        .collect::<Vec<_>>();

    HttpResponse::Ok().json(results)
}

#[get("/status")]
async fn get_status(cluster: Data<Arc<Cluster>>) -> HttpResponse {
    // TODO: need to diffentiate between alive and not alive shards
    HttpResponse::Ok().json(cluster.shards().map(shard_to_dto).collect::<Vec<_>>())
}

#[get("/shards/{shard_id}/status")]
async fn get_shard_status(cluster: Data<Arc<Cluster>>, shard_id: Path<u64>) -> HttpResponse {
    if let Some(shard) = cluster.shard(shard_id.into_inner()) {
        // TODO: need to diffentiate between alive and not alive shards
        HttpResponse::Ok().json(shard_to_dto(shard))
    } else {
        HttpResponse::NotFound().body("Shard not found")
    }
}

#[post("/shards/{shard_id}/disconnect")]
async fn post_shard_disconnect(cluster: Data<Arc<Cluster>>, shard_id: Path<u64>) -> HttpResponse {
    if let Some(shard) = cluster.shard(shard_id.into_inner()) {
        match shard.shutdown_resumable() {
            (_, Some(resume)) => HttpResponse::Ok().json(disconnect_to_dto(shard, resume)),
            _ => HttpResponse::Conflict().body("Shard is not connected"),
        }
    } else {
        HttpResponse::NotFound().body("Shard not found")
    }
}

#[tokio::main(flavor = "multi_thread")]
async fn main() {
    shared::setup();

    let manager_url = shared::unstrip_url(shared::get_env_variable("MANAGER_URL"));
    let url = shared::strip_url(shared::get_env_variable("GATEWAY_WORKER_URL"));
    let url_has_port = url.split_once(':').is_some();
    let token = shared::get_env_variable("DISCORD_TOKEN");
    let intents =
        match shared::try_get_env_variable("DISCORD_INTENTS").map(|v| u64::from_str(&v).map(Intents::from_bits)) {
            Some(Ok(Some(intents))) => intents,
            None => Intents::all() & !(Intents::GUILD_MEMBERS | Intents::GUILD_PRESENCES),
            _ => panic!("Invalid INTENTS value in env variables"),
        };

    let manager = Arc::new(manager::Client::new(&manager_url, &token));
    let sender = senders::zmq::ZmqSender::new().await;
    let (cluster, events) = twilight_gateway::Cluster::builder(&token, intents)
        .event_types(twilight_gateway::EventTypeFlags::SHARD_PAYLOAD)
        .shard_scheme(twilight_gateway::cluster::scheme::ShardScheme::try_from((0..5, 5)).unwrap())
        .build()
        .await
        .expect("Failed to make gateway connection");

    let cluster = std::sync::Arc::new(cluster);
    let start_cluster = cluster.clone();
    tokio::spawn(async move {
        start_cluster.up().await;
    });

    let ssl_key = shared::get_env_variable("MANAGER_SSL_KEY");
    let ssl_cert = shared::get_env_variable("MANAGER_SSL_CERT");
    log::info!("Starting with SSL");


    let mut server: Option<HttpServer<_, _, _, _>> = None;
    for port in 4000..5000 {
        //  Allow the port to be specified for a specific instance.
        let bind_url = if url_has_port {
            url.clone()
        } else {
            format!("{}:{}", url, port)
        };

        let mut ssl_acceptor = ssl::SslAcceptor::mozilla_intermediate(ssl::SslMethod::tls_server())
            .expect("Failed to creatte ssl acceptor");
        ssl_acceptor
            .set_private_key_file(&ssl_key, ssl::SslFiletype::PEM)
            .expect("Couldn't process private key file");
        ssl_acceptor
            .set_certificate_chain_file(&ssl_cert)
            .expect("Couldn't process certificate file");

        let bind_result = HttpServer::new(closure!(clone cluster, clone manager, clone token, || {
            App::new()
                .wrap(shared::middleware::TokenAuth::new(&token))
                .wrap(actix_web::middleware::Logger::default())
                .app_data(Data::new(cluster.clone()))
                .app_data(Data::new(manager.clone()))
                .service(post_disconnect)
                .service(get_status)
                .service(get_shard_status)
                .service(post_shard_disconnect)
        }))
        .workers(1)
        .bind_openssl(&bind_url, ssl_acceptor);

        server = match bind_result.map_err(|v| v.kind()) {
            Ok(server) => {
                log::info!("Binding to address {}", bind_url);
                Some(server)
            }
            Err(io::ErrorKind::AddrInUse) => {
                if url_has_port {
                    //  Allows the port to be specified for a specific instance.
                    panic!("Couldn't bind address {}, it's already in use", url);
                }
                log::debug!("Skipping address {}, it's already in use", bind_url);
                continue;
            }
            Err(error) => {
                panic!("Failed to bind to address {}: {:?}", bind_url, error);
            }
        };
        break;
    }

    if let Some(server) = server.map(|s| s.run()) {
        let handle = server.handle();
        futures_util::join!(
            async {
                // Todo: error handling?
                server.await.expect("Failed to start server");
                log::info!("Server stopped, closing gateway connection");
                cluster.down_resumable();
            },
            async {
                sender
                    .consume_all(Box::new(Box::pin(events.filter_map(map_event))))
                    .await;
                log::info!("Gateway stopped, closing server");
                handle.stop(true).await;
            }
        );
    } else {
        panic!("Failed to allocate any port on path {}", url)
    };
}

async fn map_event((shard_id, event): (u64, twilight_gateway::Event)) -> Option<senders::Event> {
    let event = match event {
        twilight_gateway::Event::ShardPayload(payload) => payload,
        _ => return None,
    };
    let payload = std::str::from_utf8(&event.bytes);

    if payload.is_err() {
        log::error!(
            "Ignoring payload which failed to convert to utf8: {}",
            payload.unwrap_err()
        );
        return None;
    }
    let payload = payload.unwrap();

    twilight_model::gateway::event::gateway::GatewayEventDeserializer::from_json(payload)
        .map(|v| v.event_type_ref().map(|v| v.to_owned()))
        .flatten()
        .map(move |v| (shard_id, v, event.bytes))
}
