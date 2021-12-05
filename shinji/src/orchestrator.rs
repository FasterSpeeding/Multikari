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

use actix_web::http::header;
use actix_web::HttpResponse;
use async_trait::async_trait;

#[derive(Debug)]
pub enum Error {
    RateLimitExceeded(std::time::Duration),
    ShardNotActive(u64, Option<std::time::Duration>),
    ShardNotFound(u64),
    Unhandled(Box<dyn std::error::Error>),
}

pub type Result = std::result::Result<(), Error>;

#[inline]
fn retry_to_str(duration: &std::time::Duration) -> String {
    duration.as_secs_f64().ceil().to_string()
}

impl Error {
    pub fn to_message(&self) -> &'static str {
        match self {
            Self::RateLimitExceeded(_) => "Rate limit exceeded",
            Self::ShardNotActive(..) => "Shard is not active",
            Self::ShardNotFound(_) => "Shard not found",
            Self::Unhandled(..) => "Internal server error",
        }
    }

    pub fn to_response(&self) -> actix_web::error::InternalError<&'static str> {
        let message = self.to_message();

        let result = match self {
            Self::RateLimitExceeded(duration) => HttpResponse::TooManyRequests()
                .insert_header((header::RETRY_AFTER, retry_to_str(duration)))
                .body(message),
            Self::ShardNotActive(_, duration) => {
                let mut response = HttpResponse::ServiceUnavailable();
                if let Some(duration) = duration.as_ref().map(retry_to_str) {
                    response.insert_header((header::RETRY_AFTER, duration));
                }

                response.body(message)
            }
            Self::ShardNotFound(_) => HttpResponse::NotFound().body(message),
            Self::Unhandled(_) => HttpResponse::InternalServerError().body(message),
        };

        actix_web::error::InternalError::from_response(message, result)
    }
}

impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        write!(f, "{}", self.to_message())
    }
}

impl std::error::Error for Error {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        match self {
            Self::Unhandled(err) => Some(&**err),
            _ => None,
        }
    }
}

#[async_trait]
pub trait Orchestrator {
    fn get_shard_count(&self) -> u64;
    fn get_guild_shard(&self, guild_id: u64) -> u64;
    async fn send_to_all(&self, data: &[u8]) -> Result;
    async fn send_to_shard(&self, shard_id: u64, data: &[u8]) -> Result;
}


#[derive(Clone, Debug)]
pub struct ZmqOrchestrator {
    shard_count: u64,
}

impl ZmqOrchestrator {
    pub fn new() -> Self {
        Self { shard_count: 0 }
    }
}

#[async_trait]
impl Orchestrator for ZmqOrchestrator {
    fn get_shard_count(&self) -> u64 {
        self.shard_count
    }

    fn get_guild_shard(&self, guild_id: u64) -> u64 {
        (guild_id >> 22) % self.shard_count
    }

    async fn send_to_all(&self, data: &[u8]) -> Result {
        Err(Error::RateLimitExceeded(std::time::Duration::from_secs(999999)))
    }

    async fn send_to_shard(&self, shard_id: u64, data: &[u8]) -> Result {
        Err(Error::ShardNotFound(shard_id))
    }
}