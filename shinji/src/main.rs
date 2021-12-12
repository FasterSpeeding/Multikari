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
use std::fmt;
use std::result::Result;
use std::sync::Arc;

use actix_web::error::InternalError;
use actix_web::http::StatusCode;
use actix_web::{get, patch, post, web, App, HttpRequest, HttpResponse, HttpServer};
use openssl::ssl::{SslAcceptor, SslFiletype, SslMethod};
use rand::Rng;
use shared::dto;
mod orchestrator;
use shared::middleware;


#[derive(Debug)]
struct FailedRequest {
    message: String,
    status_code: u16,
}

impl FailedRequest {
    fn new(message: &str, status_code: u16) -> Self {
        Self {
            message: message.to_owned(),
            status_code,
        }
    }
}

impl fmt::Display for FailedRequest {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        write!(
            f,
            "Request failed with generic error: {} - {}",
            self.status_code, self.message
        )
    }
}

impl std::error::Error for FailedRequest {
}


async fn get_gateway_bot(token: &str) -> Result<dto::GatewayBot, Box<dyn std::error::Error>> {
    let client = reqwest::Client::new();
    let mut attempts: u16 = 0;

    loop {
        let response = client
            .get("https://discord.com/api/gateway/bot")
            .header(reqwest::header::AUTHORIZATION, format!("Bot {}", token))
            .send()
            .await?;

        let status = response.status();
        match status.as_u16() {
            200..=299 => return response.json().await.map_err(Box::from),
            429 | 500 | 502 | 503 | 504 => {
                attempts += 1;
                if attempts > 5 {
                    return Err(Box::from(FailedRequest::new(
                        "Too many failed attempts",
                        status.as_u16(),
                    )));
                }
                let retry_after = response
                    .headers()
                    .get(reqwest::header::RETRY_AFTER)
                    .and_then(|v| v.to_str().ok())
                    .and_then(|v| v.parse::<f64>().ok())
                    .unwrap_or_else(|| 2f64.powf(attempts.into()) + rand::thread_rng().gen_range(0.0..1.0));

                log::warn!("{} - Retrying in {:.3} seconds", status, retry_after);
                tokio::time::sleep(std::time::Duration::from_secs_f64(retry_after)).await;
                continue;
            }
            _ => {
                response.error_for_status()?;
                return Err(Box::from(FailedRequest::new(
                    status.canonical_reason().unwrap_or("Unknown error"),
                    status.as_u16(),
                )));
            }
        }
    }
}


#[get("/shards/{shard_id}")]
async fn get_shard_by_id(
    shard_id: web::Path<u64>,
    orch: web::Data<Arc<dyn orchestrator::Orchestrator>>,
) -> Result<HttpResponse, InternalError<&'static str>> {
    let shard = orch
        .get_shard(shard_id.into_inner())
        .await
        .ok_or_else(|| InternalError::new("Shard not found", StatusCode::NOT_FOUND))?
        .to_dto();

    Ok(HttpResponse::Ok().json(shard))
}

#[get("/shards")]
async fn get_shards(
    orch: web::Data<Arc<dyn orchestrator::Orchestrator>>,
) -> Result<HttpResponse, InternalError<&'static str>> {
    let shards: Vec<_> = orch.get_shards().await.iter().map(|v| v.to_dto()).collect();
    Ok(HttpResponse::Ok().json(shards))
}

#[get("/shards/{shard_id}/presence")]
async fn get_shard_presence(_req: HttpRequest) -> Result<HttpResponse, InternalError<&'static str>> {
    Ok(HttpResponse::Ok().finish())
}

#[patch("/shards/{shard_id}/presence")]
async fn patch_shard_presence(
    shard_id: web::Path<u64>,
    data: web::Json<dto::PresenceUpdate>,
    orch: web::Data<Arc<dyn orchestrator::Orchestrator>>,
) -> Result<HttpResponse, InternalError<&'static str>> {
    // TODO: are these case-sensitive?
    if !["online", "dnd", "idle", "invisible", "offline"].contains(&data.status.as_ref()) {
        return Err(InternalError::new("Invalid presence status", StatusCode::BAD_REQUEST));
    };

    // Since this was parsed from Json, we can assume it's valid Json.
    let json = serde_json::value::to_value(&data.into_inner()).unwrap();
    orch.send_to_shard(shard_id.into_inner(), json.to_string().as_bytes())
        .await
        .map_err(|e| e.to_response())?;

    Ok(HttpResponse::NoContent().finish())
}

#[post("/guilds/{guild_id}/request-members")]
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

    Ok(HttpResponse::Accepted().finish())
}

#[patch("/guilds/{guild_id}/voice-state")]
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

#[tokio::main(flavor = "current_thread")]
async fn main() -> std::io::Result<()> {
    shared::setup();

    let url = shared::strip_url(shared::get_env_variable("MANAGER_URL"));
    let token = shared::get_env_variable("DISCORD_TOKEN");
    let gateway_bot = get_gateway_bot(&token).await.expect("Failed to fetch Gateway Bot info");
    let shard_count = shared::try_get_env_variable("SHARD_COUNT")
        .map(|v| v.parse().expect("Invalid SHARD_COUNT env variable"))
        .unwrap_or(gateway_bot.shards);

    let orch = Arc::from(orchestrator::ZmqOrchestrator::new(shard_count));
    let mut server = HttpServer::new(move || {
        App::new()
            .app_data(web::Data::new(Arc::clone(&orch) as Arc<dyn orchestrator::Orchestrator>))
            .wrap(middleware::TokenAuth::new(&token))
            .wrap(actix_web::middleware::Logger::default())
            .service(get_shard_by_id)
            .service(get_shards)
            .service(request_members)
            .service(patch_guild_voice_state)
            .service(patch_shard_presence)
    });

    let ssl_key = shared::get_env_variable("MANAGER_SSL_KEY");
    let ssl_cert = shared::get_env_variable("MANAGER_SSL_CERT");
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

    server
        .workers(1) // This only needs 1 thread, any more would be excessive lol.
        .run()
        .await
}
