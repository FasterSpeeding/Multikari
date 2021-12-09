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

use futures_util::StreamExt;
use twilight_gateway::{cluster, Event, EventTypeFlags, Intents};
use twilight_model::gateway::event::gateway::GatewayEventDeserializer;
mod sender;
use sender::Sender;

#[tokio::main]
async fn main() {
    let dotenv_result = shared::load_env();
    shared::setup_logging();

    if let Err(error) = dotenv_result {
        log::info!("Couldn't load .env file: {}", error);
    }

    let token = shared::get_env_variable("DISCORD_TOKEN").expect("DISCORD_TOKEN env variable not found");
    let intents = match shared::get_env_variable("DISCORD_INTENTS").map(|v| u64::from_str(&v).map(Intents::from_bits)) {
        Some(Ok(Some(intents))) => intents,
        None => Intents::all() & !(Intents::GUILD_MEMBERS | Intents::GUILD_PRESENCES),
        _ => panic!("Invalid INTENTS value in env variables"),
    };

    let sender = sender::ZmqSender::build().await;

    let (cluster, events) = cluster::Cluster::builder(token, intents)
        .event_types(EventTypeFlags::SHARD_PAYLOAD)
        .build()
        .await
        .expect("Failed to make gateway connection");

    let cluster = std::sync::Arc::new(cluster);

    tokio::spawn(async move {
        cluster.clone().up().await;
    });

    let filtered = events.filter_map(async move |event| {
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
    });
    sender.consume_all(Box::new(Box::pin(filtered))).await;
}
