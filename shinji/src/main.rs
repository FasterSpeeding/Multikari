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
use std::result::Result;
use std::sync::Arc;

use actix_web::error::InternalError;
use actix_web::http::StatusCode;
use actix_web::{get, patch, post, web, App, HttpRequest, HttpResponse, HttpServer};
use openssl::ssl::{SslAcceptor, SslFiletype, SslMethod};
use shared::dto;
mod orchestrator;

#[get("/shards/{shard_id}")]
async fn get_shard_by_id(
    shard_id: web::Path<u64>,
    orchestrator: web::Data<Arc<dyn orchestrator::Orchestrator>>,
) -> Result<HttpResponse, InternalError<&'static str>> {
    Ok(HttpResponse::NoContent().finish())
}

#[get("/shards")]
async fn get_shards(
    orchestrator: web::Data<Arc<dyn orchestrator::Orchestrator>>,
) -> Result<HttpResponse, InternalError<&'static str>> {
    Ok(HttpResponse::NoContent().finish())
}

#[patch("/shards/{shard_id}/presence")]
async fn patch_shard_presence(
    shard_id: web::Path<u64>,
    data: web::Json<dto::PresenceUpdate>,
    orch: web::Data<Arc<dyn orchestrator::Orchestrator>>,
) -> Result<HttpResponse, InternalError<&'static str>> {
    // TODO: are these case-sensitive?
    if !["online", "dnd", "idle", "invisibile", "offline"].contains(&data.status.as_ref()) {
        return Err(InternalError::new("Invalid presence status", StatusCode::BAD_REQUEST));
    };

    // Since this was parsed from Json, we can assume it's valid Json.
    let json = serde_json::value::to_value(&data.into_inner()).unwrap();
    orch.send_to_shard(shard_id.into_inner(), json.to_string().as_bytes())
        .await
        .map_err(|e| e.to_response())?;

    Ok(HttpResponse::NoContent().finish())
}

#[post("/guilds/{guild_id}/request_members")]
async fn request_members(
    guild_id: web::Path<u64>,
    data: web::Json<dto::GuildRequestMembers>,
    orch: web::Data<Arc<dyn orchestrator::Orchestrator>>,
) -> Result<HttpResponse, InternalError<&'static str>> {
    let guild_id = guild_id.into_inner();
    let shard_id = orch.get_guild_shard(guild_id);

    // Since this was parsed from Json, we can assume it's valid Json.
    let mut json = serde_json::value::to_value(&data.into_inner()).unwrap();
    json["guild_id"] = guild_id.into();

    orch.send_to_shard(shard_id, json.to_string().as_bytes())
        .await
        .map_err(|e| e.to_response())?;

    Ok(HttpResponse::NoContent().finish())
}

#[patch("/guilds/{guild_id}/voice_state")]
async fn patch_guild_voice_state(
    guild_id: web::Path<u64>,
    data: web::Json<dto::VoiceStateUpdate>,
    orch: web::Data<Arc<dyn orchestrator::Orchestrator>>,
) -> Result<HttpResponse, InternalError<&'static str>> {
    let guild_id = guild_id.into_inner();
    let shard_id = orch.get_guild_shard(guild_id);

    // Since this was parsed from Json, we can assume it's valid Json.
    let mut json = serde_json::value::to_value(&data.into_inner()).unwrap();
    json["guild_id"] = guild_id.into();

    orch.send_to_shard(shard_id, json.to_string().as_bytes())
        .await
        .map_err(|e| e.to_response())?;

    Ok(HttpResponse::NoContent().finish())
}

async fn actix_main() -> std::io::Result<()> {
    let ssl_config = (
        shared::get_env_variable("SSL_KEY"),
        shared::get_env_variable("SSL_CERT"),
    );
    let url = shared::get_env_variable("URL").expect("Missing URL env variable");

    let orch = orchestrator::ZmqOrchestrator::new();
    let mut server = HttpServer::new(move || {
        App::new()
            .app_data(web::Data::new(
                Arc::from(orch.clone()) as Arc<dyn orchestrator::Orchestrator>
            ))
            .service(get_shard_by_id)
            .service(get_shards)
            .service(request_members)
            .service(patch_guild_voice_state)
            .service(patch_shard_presence)
    });

    match ssl_config {
        (Some(ssl_key), Some(ssl_cert)) => {
            log::info!("Starting with SSL");
            let mut ssl_acceptor =
                SslAcceptor::mozilla_intermediate(SslMethod::tls_server()).expect("Failed to creatte ssl acceptor");
            ssl_acceptor
                .set_private_key_file(&ssl_key, SslFiletype::PEM)
                .expect("Couldn't process private key file");
            ssl_acceptor
                .set_certificate_chain_file(&ssl_cert)
                .expect("Couldn't process certificate file");

            server = server.bind_openssl(&url, ssl_acceptor)?;
        }
        (None, None) => {
            log::info!("No SSL key/cert provided, starting without SSL");
            server = server.bind(&url)?;
        }
        _ => {
            log::warn!("Missing SSL_KEY or SSL_CERT, both are required for SSL");
            server = server.bind(&url)?;
        }
    }

    server.run().await
}

fn main() -> std::io::Result<()> {
    let dotenv_result = shared::load_env();
    shared::setup_logging();

    if let Err(error) = dotenv_result {
        log::info!("Couldn't load .env file: {}", error);
    }

    actix_web::rt::System::with_tokio_rt(|| {
        tokio::runtime::Builder::new_multi_thread()
            .enable_all()
            .build()
            .unwrap()
    })
    .block_on(actix_main())
}
