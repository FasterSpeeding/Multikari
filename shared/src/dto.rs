// BSD 3-Clause License
//
// Copyright (c) 2021-2022, Lucina
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
use serde::{Deserialize, Deserializer, Serialize};
use serde_repr::{Deserialize_repr, Serialize_repr};


// Any value that is present is considered Some value, including null.
fn deserialize_some<'de, T, D>(deserializer: D) -> Result<Option<T>, D::Error>
where
    T: Deserialize<'de>,
    D: Deserializer<'de>, {
    Deserialize::deserialize(deserializer).map(Some)
}

//  Discord Package

#[derive(Debug, Deserialize)]
pub struct SessionStartLimit {
    pub total: u64,
    pub remaining: u64,
    pub reset_after: u64,
    pub max_concurrency: u64,
}

#[derive(Debug, Deserialize)]
pub struct GatewayBot {
    pub url: String,
    pub shards: u64,
    pub session_start_limit: SessionStartLimit,
}

// Metadata

#[derive(Debug, Deserialize, Serialize)]
pub struct Shard {
    pub heartbeat_latency: Option<f64>,
    pub is_alive: bool,
    pub seq: Option<u64>,
    pub session_id: Option<String>,
    pub shard_id: u64,
}

// Gateway Requests

#[derive(Debug, Deserialize, Serialize)]
pub struct GuildRequestMembers {
    #[serde(
        default,
        deserialize_with = "deserialize_some",
        skip_serializing_if = "Option::is_none"
    )]
    pub query: Option<String>,
    #[serde(
        default,
        deserialize_with = "deserialize_some",
        skip_serializing_if = "Option::is_none"
    )]
    pub limit: Option<u64>,
    #[serde(
        default,
        deserialize_with = "deserialize_some",
        skip_serializing_if = "Option::is_none"
    )]
    pub presences: Option<bool>,
    #[serde(
        default,
        deserialize_with = "deserialize_some",
        skip_serializing_if = "Option::is_none"
    )]
    pub user_ids: Option<Vec<u64>>, //  TODO: is there a length limit here lol?
    #[serde(
        default,
        deserialize_with = "deserialize_some",
        skip_serializing_if = "Option::is_none"
    )]
    pub nonce: Option<String>,
}

#[derive(Debug, Deserialize, Serialize)]
pub struct VoiceStateUpdate {
    // TODO: is channel_id actually optional?
    #[serde(
        default,
        deserialize_with = "deserialize_some",
        skip_serializing_if = "Option::is_none"
    )]
    pub channel_id: Option<Option<u64>>,
    #[serde(
        default,
        deserialize_with = "deserialize_some",
        skip_serializing_if = "Option::is_none"
    )]
    pub self_mute: Option<bool>,
    #[serde(
        default,
        deserialize_with = "deserialize_some",
        skip_serializing_if = "Option::is_none"
    )]
    pub self_deaf: Option<bool>,
}

#[repr(i8)]
#[derive(Debug, Deserialize_repr, Serialize_repr)]
pub enum ActivityType {
    Game,
    Streaming,
    Listening,
    Watching,
    Competing = 5,
}

#[derive(Debug, Deserialize, Serialize)]
pub struct Activity {
    pub name: String,
    pub r#type: ActivityType,
    #[serde(
        default,
        deserialize_with = "deserialize_some",
        skip_serializing_if = "Option::is_none"
    )]
    pub url: Option<Option<String>>, // TODO: what happens if url is null for a type which doesn't take url?
}

#[derive(Debug, Deserialize, Serialize)]
pub struct PresenceUpdate {
    // TODO: can this just not be included?
    pub since: Option<u64>,
    pub activities: Vec<Activity>, // TODO: what's the max amount?
    pub status: String,
    #[serde(default)] // TODO: is this optional on the actual api?
    pub afk: bool, //  TODO: also what happens if this isn't included and they're already afk?
}
