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
use actix_web::http::header::HttpDate;
use actix_web::{get, patch, post, web, HttpRequest, HttpResponse};
use shared::dto;

#[get("/shards/{shard_id}")]
async fn get_shard_by_id(req: HttpRequest, shard_id: web::Path<u64>) -> HttpResponse {
    HttpResponse::Ok().finish()
}

#[get("/shards")]
async fn get_shards(req: HttpRequest) -> HttpResponse {
    HttpResponse::Ok().finish()
}

#[post("/guilds/{guild_id}/request_members")]
async fn request_members(
    req: HttpRequest,
    guild_id: web::Path<u64>,
    data: web::Json<dto::GuildRequestMembers>,
) -> HttpResponse {
    HttpResponse::Ok().finish()
}

#[patch("/guilds/{guild_id}/voice_state")]
async fn patch_guild_voice_state(
    req: HttpRequest,
    guild_id: web::Path<u64>,
    status: web::Json<dto::VoiceStateUpdate>,
) -> HttpResponse {
    HttpResponse::Ok().finish()
}

#[patch("/presences")]
async fn patch_presences(req: HttpRequest, body: web::Json<dto::PresenceUpdate>) -> HttpResponse {
    HttpResponse::Ok().finish()
}

#[patch("/shards/{shard_id}/presence")]
async fn patch_shard_presence(
    req: HttpRequest,
    shard_id: web::Path<u64>,
    body: web::Json<dto::PresenceUpdate>,
) -> HttpResponse {
    HttpResponse::Ok().finish()
}

fn main() {
    let dotenv_result = shared::load_env();
    shared::setup_logging();

    if let Err(error) = dotenv_result {
        log::info!("Couldn't load .env file: {}", error);
    }

    println!("Hello, world!");
}
