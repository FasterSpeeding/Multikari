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
use futures_util::StreamExt;
use std::str::FromStr;
use twilight_gateway::{cluster, Event, EventTypeFlags, Intents};
// use abc;
mod sender;
mod utility;
use sender::Sender;

// trait

pub fn setup_logging() {
    let level = match utility::get_env_variable("LOG_LEVEL").map(|v| log::LevelFilter::from_str(&v))
    {
        Some(Err(_)) => {
            panic!("Invalid log level provided, expected TRACE, DEBUG, INFO, WARN or ERROR")
        }
        Some(Ok(level)) => level,
        None => log::LevelFilter::Info,
    };

    simple_logger::SimpleLogger::new()
        .with_level(level)
        .init()
        .expect("Failed to set up logger");
}

#[tokio::main]
async fn main() {
    let dotenv_result = dotenv::dotenv();
    setup_logging();

    if let Err(error) = dotenv_result {
        log::info!("Couldn't load .env file: {}", error);
    }

    let token =
        utility::get_env_variable("DISCORD_TOKEN").expect("DISCORD_TOKEN env variable not found");
    let intents = match utility::get_env_variable("DISCORD_INTENTS")
        .map(|v| u64::from_str(&v).map(Intents::from_bits))
    {
        Some(Ok(Some(intents))) => intents,
        None => Intents::all() & !(Intents::GUILD_MEMBERS | Intents::GUILD_PRESENCES),
        _ => panic!("Invalid INTENTS value in env variables"),
    };

    let sender = sender::ZmqSender::build().await;

    let (cluster, mut events) = cluster::Cluster::builder(token, intents)
        .event_types(EventTypeFlags::SHARD_PAYLOAD)
        .build()
        .await
        .expect("Failed to make gateway connection");

    let cluster = std::sync::Arc::new(cluster);

    tokio::spawn(async move {
        cluster.clone().up().await;
    });

    while let Some(event) = events.next().await {
        let (shard_id, event) = match event {
            (shard_id, Event::ShardPayload(payload)) => (shard_id, payload),
            _ => continue,
        };
        let payload = std::str::from_utf8(&event.bytes);

        if payload.is_err() {
            continue;
        }
        let payload = payload.unwrap();

        if let Some(event) =
            twilight_model::gateway::event::gateway::GatewayEventDeserializer::from_json(payload)
        {
            if let Some(event_type) = event.event_type_ref() {
                sender.consume_event(shard_id, event_type, payload).await;
            }
        }
    }
}
