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
use std::str::FromStr;

use actix_web::{get, patch, post, web, App, HttpRequest, HttpResponse, HttpServer};
use closure::closure;
use futures_util::StreamExt;
use shared::middleware;
use twilight_gateway::{Cluster, Event, EventTypeFlags, Intents};
use twilight_model::gateway::event::gateway::GatewayEventDeserializer;
mod manager;
use openssl::ssl::{SslAcceptor, SslFiletype, SslMethod};
use senders::Sender;
mod senders;
use std::io;
use std::sync::Arc;

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
    let (cluster, events) = Cluster::builder(&token, intents)
        .event_types(EventTypeFlags::SHARD_PAYLOAD)
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

        let mut ssl_acceptor =
            SslAcceptor::mozilla_intermediate(SslMethod::tls_server()).expect("Failed to creatte ssl acceptor");
        ssl_acceptor
            .set_private_key_file(&ssl_key, SslFiletype::PEM)
            .expect("Couldn't process private key file");
        ssl_acceptor
            .set_certificate_chain_file(&ssl_cert)
            .expect("Couldn't process certificate file");

        let bind_result = HttpServer::new(closure!(clone cluster, clone manager, clone token, || {
            App::new()
                .wrap(middleware::TokenAuth::new(&token))
                .app_data(web::Data::new(cluster.clone()))
                .app_data(web::Data::new(manager.clone()))
            // .service(get_shard_by_id)
        }))
        .bind_openssl(&bind_url, ssl_acceptor);

        server = match bind_result.map_err(|v| v.kind()) {
            Ok(server) => {
                log::info!("Binding to address {}", bind_url);
                Some(server)
            }
            Err(io::ErrorKind::AddrInUse) => {
                if url_has_port {
                    //  Allow the port to be specified for a specific instance.
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

    if let Some(server) = server {
        // TODO: consider using try_join
        futures_util::try_join!(server.run(), async {
            sender
                .consume_all(Box::new(Box::pin(events.filter_map(map_event))))
                .await;
            Ok(())
        })
        .expect("Failed to start")
    } else {
        panic!("Failed to allocate any port on path {}", url)
    };
}

async fn map_event(event: (u64, twilight_gateway::Event)) -> Option<senders::Event> {
    let (shard_id, event) = match event {
        (shard_id, Event::ShardPayload(payload)) => (shard_id, payload),
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

    GatewayEventDeserializer::from_json(payload)
        .map(|v| v.event_type_ref().map(|v| v.to_owned()))
        .flatten()
        .map(move |v| (shard_id, v, event.bytes))
}
