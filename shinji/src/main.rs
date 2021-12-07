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

#[inline]
fn invalid_token() -> InternalError<&'static str> {
    InternalError::new("Missing or invalid authorization header", StatusCode::UNAUTHORIZED)
}


// TODO: this is never gonna happen cause i'm too dumb to understand the docs
// but could this be made a middleware which just apples to every endpoint?
struct Token {
    token: String,
}

impl Token {
    pub fn new(token: &str) -> Self {
        Self {
            token: token.to_owned(),
        }
    }

    fn check(&self, req: &HttpRequest) -> Result<(), InternalError<&'static str>> {
        let (token_type, auth) = req
            .headers()
            .get("Authorization")
            .map(|v| v.to_str().ok())
            .flatten()
            .map(|v| v.split_once(" "))
            .flatten()
            .ok_or_else(invalid_token)?;

        if !token_type.eq_ignore_ascii_case("Basic") {
            return Err(invalid_token());
        }

        let raw_auth_parts = base64::decode(auth).map_err(|_| invalid_token())?;
        let auth_parts = String::from_utf8_lossy(&raw_auth_parts);
        if auth_parts.split_once(":").ok_or_else(invalid_token)?.1 != self.token {
            Err(InternalError::new("Unknown token", StatusCode::UNAUTHORIZED))
        } else {
            Ok(())
        }
    }
}


#[get("/shards/{shard_id}")]
async fn get_shard_by_id(
    req: HttpRequest,
    shard_id: web::Path<u64>,
    orch: web::Data<Arc<dyn orchestrator::Orchestrator>>,
    token: web::Data<Token>,
) -> Result<HttpResponse, InternalError<&'static str>> {
    token.check(&req)?;
    let shard = orch
        .get_shard(shard_id.into_inner())
        .await
        .ok_or_else(|| InternalError::new("Shard not found", StatusCode::NOT_FOUND))?
        .to_dto();

    Ok(HttpResponse::Ok().json(shard))
}

#[get("/shards")]
async fn get_shards(
    req: HttpRequest,
    orch: web::Data<Arc<dyn orchestrator::Orchestrator>>,
    token: web::Data<Token>,
) -> Result<HttpResponse, InternalError<&'static str>> {
    token.check(&req)?;
    let shards: Vec<_> = orch.get_shards().await.iter().map(|v| v.to_dto()).collect();
    Ok(HttpResponse::Ok().json(shards))
}

#[patch("/shards/{shard_id}/presence")]
async fn patch_shard_presence(
    req: HttpRequest,
    shard_id: web::Path<u64>,
    data: web::Json<dto::PresenceUpdate>,
    orch: web::Data<Arc<dyn orchestrator::Orchestrator>>,
    token: web::Data<Token>,
) -> Result<HttpResponse, InternalError<&'static str>> {
    token.check(&req)?;
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
    req: HttpRequest,
    guild_id: web::Path<u64>,
    data: web::Json<dto::GuildRequestMembers>,
    orch: web::Data<Arc<dyn orchestrator::Orchestrator>>,
    token: web::Data<Token>,
) -> Result<HttpResponse, InternalError<&'static str>> {
    token.check(&req)?;
    let guild_id = guild_id.into_inner();
    let shard_id = orch.get_guild_shard(guild_id);

    // Since this was parsed from Json, we can assume it's valid Json.
    let mut json = serde_json::value::to_value(&data.into_inner()).unwrap();
    json["guild_id"] = guild_id.into();

    orch.send_to_shard(shard_id, json.to_string().as_bytes())
        .await
        .map_err(|e| e.to_response())?;

    Ok(HttpResponse::Accepted().finish())
}

#[patch("/guilds/{guild_id}/voice_state")]
async fn patch_guild_voice_state(
    req: HttpRequest,
    guild_id: web::Path<u64>,
    data: web::Json<dto::VoiceStateUpdate>,
    orch: web::Data<Arc<dyn orchestrator::Orchestrator>>,
    token: web::Data<Token>,
) -> Result<HttpResponse, InternalError<&'static str>> {
    token.check(&req)?;
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
    let url = shared::get_env_variable("URL").expect("Missing URL env variable");
    let shard_count: u64 = shared::get_env_variable("SHARD_COUNT")
        .expect("Missing SHARD_COUNT env variable")
        .parse()
        .expect("Invalid SHARD_COUNT env variable");
    let token = shared::get_env_variable("TOKEN").expect("Missing TOKEN env variable");

    let orch = Arc::from(orchestrator::ZmqOrchestrator::new(shard_count));
    let mut server = HttpServer::new(move || {
        App::new()
            .app_data(web::Data::new(Arc::clone(&orch) as Arc<dyn orchestrator::Orchestrator>))
            .app_data(web::Data::new(Token::new(&token)))
            .service(get_shard_by_id)
            .service(get_shards)
            .service(request_members)
            .service(patch_guild_voice_state)
            .service(patch_shard_presence)
    });

    let ssl_config = (
        shared::get_env_variable("SSL_KEY"),
        shared::get_env_variable("SSL_CERT"),
    );
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

    server
        .workers(1) // This only needs 1 thread, any more would be excessive lol.
        .run()
        .await
}

fn main() -> std::io::Result<()> {
    let dotenv_result = shared::load_env();
    shared::setup_logging();

    if let Err(error) = dotenv_result {
        log::info!("Couldn't load .env file: {}", error);
    }

    actix_web::rt::System::with_tokio_rt(|| {
        tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .unwrap()
    })
    .block_on(actix_main())
}
