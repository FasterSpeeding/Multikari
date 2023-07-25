use std::error::Error;
// BSD 3-Clause License
//
// Copyright (c) 2021-2023, Lucina
// All rights reserved.
//
// Redistribution and use in source and binary forms, with or without
// modification, are permitted provided that the following conditions are met:
//
// * Redistributions of source code must retain the above copyright notice, this list of conditions and the
//   following disclaimer.
//
// * Redistributions in binary form must reproduce the above copyright notice, this list of conditions and the
//   following disclaimer in the documentation and/or other materials provided with the distribution.
//
// * Neither the name of the copyright holder nor the names of its contributors may be used to endorse or promote
//   products derived from this software without specific prior written permission.
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
use std::str::FromStr;
use std::time::{Duration, Instant};

use futures::channel::mpsc;
use futures::{SinkExt, StreamExt};
use hyper::client::ResponseFuture;
use tokio::fs::File;
use tokio::io::AsyncReadExt;
use tonic::metadata::MetadataValue;
use tonic::Request;
use tower::util::ServiceFn;
use twilight_model::gateway::event::gateway::GatewayEventDeserializer;
use twilight_model::gateway::payload::incoming::Ready;
use twilight_model::gateway::payload::outgoing::{request_guild_members, update_presence, update_voice_state};
use twilight_model::gateway::presence::{Activity, ActivityType, Status};
use twilight_model::gateway::OpCode;
use twilight_model::id::Id;
mod senders;
use hyper::client::connect::HttpConnector;
use hyper::{Client, Uri};
use hyper_openssl::HttpsConnector;
use openssl::ssl::{SslConnector, SslMethod};
use openssl::x509::X509;
use senders::Sender;
use tonic_openssl::ALPN_H2_WIRE;
use twilight_gateway::{CloseFrame, Intents};

mod utility;

tonic::include_proto!("_");

fn try_get_int_variable(name: &str) -> Option<u64> {
    utility::try_get_env_variable("name")
        .map(|v| u64::from_str(&v))
        .transpose()
        .unwrap_or_else(|_| panic!("Failed to parse {name}"))
}


fn setup() {
    let dotenv_result = dotenv::dotenv();
    simple_logger::init_with_env().expect("Failed to set up logger");

    if let Err(error) = dotenv_result {
        log::info!("Couldn't load .env file: {}", error);
    }
}

// Openssl is used here instead of Rustls since it's easier to use self-signed
// CA certs with.
async fn _tls_client(
    url: Uri,
) -> Result<ServiceFn<impl Fn(hyper::Request<tonic::body::BoxBody>) -> ResponseFuture>, Box<dyn Error>> {
    let mut http = HttpConnector::new();
    http.enforce_http(false);

    let mut connector = SslConnector::builder(SslMethod::tls())?;

    if let Some(path) = utility::try_get_env_variable("ORCHESTRATOR_CA_CERT") {
        let mut buffer = Vec::new();
        File::open(path)
            .await
            .expect("Couldn't read orchestrator CA cert")
            .read_to_end(&mut buffer)
            .await
            .expect("Couldn't read orchestrator CA cert");

        let cert = X509::from_pem(&buffer).unwrap();
        connector.cert_store_mut().add_cert(cert)?;
        connector.set_alpn_protos(ALPN_H2_WIRE)?;
    };

    let hyper = Client::builder()
        .http2_only(true)
        .build(HttpsConnector::with_connector(http, connector)?);

    Ok(tower::service_fn(move |mut req: hyper::Request<_>| {
        let mut url_parts = url.clone().into_parts();
        url_parts.path_and_query = req.uri().path_and_query().cloned();
        *req.uri_mut() = Uri::from_parts(url_parts).unwrap();

        hyper.request(req)
    }))
}

#[tokio::main(flavor = "multi_thread")]
async fn main() {
    setup();

    let shard_count = try_get_int_variable("SHARD_COUNT").unwrap_or(1);
    // TODO: add metadata rpc method to server to get this
    let shard_total = try_get_int_variable("SHARD_TOTAL").unwrap_or(1);

    let url = utility::get_env_variable("ORCHESTRATOR_URL");
    let url = tonic::transport::Uri::from_str(&url).unwrap();
    let token = utility::get_env_variable("DISCORD_TOKEN");
    let intents =
        match utility::try_get_env_variable("DISCORD_INTENTS").map(|v| u64::from_str(&v).map(Intents::from_bits)) {
            Some(Ok(Some(intents))) => intents,
            None => Intents::all() & !(Intents::GUILD_MEMBERS | Intents::GUILD_PRESENCES),
            _ => panic!("Invalid INTENTS value in env variables"),
        };

    let auth_hash = hex::encode(
        nacl::scrypt(
            token.as_bytes(),
            token.rsplit('.').last().unwrap().as_bytes(),
            11, // Log 2048
            8,
            1,
            64,
            &|_| {},
        )
        .unwrap(),
    );
    let auth_header = MetadataValue::from_str(&("Bearer ".to_string() + &auth_hash)).unwrap();

    let sender = senders::zmq::ZmqSender::new();
    let mut joins: Vec<tokio::task::JoinHandle<()>> = Vec::new();
    for _ in 0..shard_count {
        let auth_header = auth_header.clone();
        let channel = _tls_client(url.clone()).await.unwrap();
        let mut client =
            orchestrator_client::OrchestratorClient::with_interceptor(channel, move |mut req: Request<_>| {
                req.metadata_mut().insert("authorization", auth_header.clone());
                Ok(req)
            });

        let sender = sender.clone();
        let token = token.clone();
        joins.push(tokio::spawn(async move {
            let (mut send_state, recv_state) = mpsc::unbounded();
            let mut stream = client.acquire_next(recv_state).await.unwrap().into_inner();

            let instruction = stream.message().await;

            // TODO: handle error and disconnect
            let instruction = match instruction {
                Err(err) => unimplemented!("{} unexpected error", err),
                // TODO: log
                Ok(None) => return,
                Ok(Some(instruction)) if instruction.r#type == 2 => instruction,
                // TODO: properly check for DISCONNECTS, possible shard_id and
                // other unexpected cases
                _ => unimplemented!("Unexpectec cases"),
            };
            let shard_id =
                twilight_model::gateway::ShardId::new(instruction.shard_id.unwrap().try_into().unwrap(), shard_total);

            let shard = twilight_gateway::Shard::new(shard_id, token, intents);
            // TODO: this message shouldn't be ignored. Also what even is it?
            // Although right now it is likely just a heartbeat
            let gateway_url = &instruction.shard_state.as_ref().unwrap().gateway_url;
            send_state.feed(to_state(&shard, gateway_url)).await.unwrap();

            let send_command = shard.sender();
            tokio::join!(
                handle_events(shard, sender, send_state, instruction.shard_state.unwrap()),
                handle_instructions(stream, send_command),
            );
        }));
    }

    futures::future::join_all(joins).await;
}

fn to_state(shard: &twilight_gateway::Shard, gateway_url: &str) -> Shard {
    let (session_id, seq) = shard
        .session()
        .map(|v| (Some(v.id().to_string()), Some(v.sequence() as i64)))
        .unwrap_or_else(|| (None, None));

    let latency = shard
        .latency()
        .recent()
        .first()
        .map(|v| v.as_secs_f64())
        .unwrap_or(f64::NAN);

    Shard {
        state: if shard.status().is_disconnected() { 2 } else { 1 },
        last_seen: None,
        latency,
        session_id,
        seq,
        shard_id: shard.id().number() as i64,
        gateway_url: gateway_url.to_string(),
    }
}

const _STATE_TIME: Duration = Duration::new(30, 0);

async fn handle_events(
    mut shard: twilight_gateway::Shard,
    sender: senders::zmq::ZmqSender,
    mut send_state: mpsc::UnboundedSender<Shard>,
    shard_state: Shard,
) {
    let shard_id = shard.id().number();
    let mut update_state_at = Instant::now() - _STATE_TIME;
    let mut gateway_url = shard_state.gateway_url;

    let stream = async_stream::stream! {
        loop {
            let message = shard.next_message().await;
            let now = Instant::now();
            if now.ge(&update_state_at) {
                send_state.feed(to_state(&shard, &gateway_url)).await.unwrap();
                update_state_at = now + _STATE_TIME;
            };

            let message = match message {
                Ok(message) => message,
                // TODO: handle the shard being disconnected properly
                // the server needs to be informed of this!!!
                Err(source) => break, // TODO: log
            };

            let payload = match message {
                twilight_gateway::Message::Text(payload) => payload,
                twilight_gateway::Message::Close(_) => return,
            };

            let event_name =
                GatewayEventDeserializer::from_json(&payload).and_then(|v| v.event_type().map(|v| v.to_owned()));

            if let Some(event_name) = event_name {
                if event_name.eq("READY") {
                    match serde_json::from_str::<Ready>(&payload) {
                        Ok(ready) => gateway_url = ready.resume_gateway_url,
                        Err(err) => return, // TODO: log
                    };
                };
                yield (shard_id, event_name, payload);
            }
        };
    };
    sender.consume_all(Box::new(Box::pin(stream))).await;
}

async fn handle_instructions(mut stream: tonic::Streaming<Instruction>, sender: twilight_gateway::MessageSender) {
    let mut presence = update_presence::UpdatePresencePayload {
        activities: vec![],
        afk: false,
        since: None,
        status: Status::Online,
    };

    loop {
        let instruction = match stream.next().await {
            Some(Ok(instruction)) => instruction,
            Some(Err(_)) => continue, // TODO: TODO: log
            None => break,
        };

        match instruction.r#type {
            // DISCONNECT
            0 => {
                sender.close(CloseFrame::NORMAL).unwrap();
                break;
            }
            // GATEWAY_PAYLOAD
            1 => {}
            // Unexpected (including CONNECT)
            _ => continue, // TODO: log
        };

        match instruction.payload {
            Some(instruction::Payload::PresenceUpdate(payload)) => {
                match payload.idle_since {
                    Some(presence_update::IdleSince::IdleTimestamp(timestamp)) => {
                        presence.since = Some(timestamp.seconds as u64)
                    }
                    None => presence.since = None,
                    _ => {}
                };

                let status = payload.status.map(|status| match status.as_str() {
                    "dnd" => Status::DoNotDisturb,
                    "idle" => Status::Idle,
                    "invisible" => Status::Invisible,
                    "offline" => Status::Offline,
                    "online" => Status::Online,
                    _ => unimplemented!("Shouldn't happen"),
                });
                if let Some(status) = status {
                    presence.status = status;
                };

                match payload.activity {
                    Some(presence_update::Activity::ActivityPayload(activity)) => {
                        presence.activities.clear();
                        presence.activities.push(Activity {
                            application_id: None,
                            assets: None,
                            buttons: vec![],
                            created_at: None,
                            details: None,
                            emoji: None,
                            flags: None,
                            id: None,
                            instance: None,
                            kind: ActivityType::from(u8::try_from(activity.r#type).unwrap()),
                            name: activity.name,
                            party: None,
                            secrets: None,
                            state: None,
                            timestamps: None,
                            url: activity.url,
                        })
                    }
                    Some(presence_update::Activity::UndefinedActivity(_)) => {
                        presence.activities.clear();
                    }
                    None => {}
                }

                sender.command(&update_presence::UpdatePresence {
                    op: OpCode::PresenceUpdate,
                    d: presence.clone(),
                })
            }
            Some(instruction::Payload::VoiceState(payload)) => sender.command(&update_voice_state::UpdateVoiceState {
                op: OpCode::VoiceStateUpdate,
                d: update_voice_state::UpdateVoiceStateInfo {
                    channel_id: payload.channel_id.map(|v| Id::new(v as u64)),
                    guild_id: Id::new(payload.guild_id as u64),
                    self_deaf: payload.self_deaf.unwrap_or_default(),
                    self_mute: payload.self_mute.unwrap_or_default(),
                },
            }),
            Some(instruction::Payload::RequestGuildMembers(payload)) => {
                sender.command(&request_guild_members::RequestGuildMembers {
                    op: OpCode::RequestGuildMembers,
                    d: request_guild_members::RequestGuildMembersInfo {
                        guild_id: Id::new(payload.guild_id as u64),
                        limit: Some(payload.limit as u64),
                        nonce: payload.nonce,
                        presences: payload.include_presences,
                        query: if payload.query.is_empty() {
                            None
                        } else {
                            Some(payload.query)
                        },
                        user_ids: if payload.users.is_empty() {
                            None
                        } else {
                            Some(request_guild_members::RequestGuildMemberId::Multiple(
                                payload.users.iter().map(|v| Id::new(*v as u64)).collect(),
                            ))
                        },
                    },
                })
            }
            None => continue, // TODO: log
        }
        .unwrap();
    }
}
