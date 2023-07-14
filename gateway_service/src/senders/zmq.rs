// BSD 3-Clause License
//
// Copyright (c) 2021-2023, Lucina
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
use async_trait::async_trait;
use futures::{SinkExt, StreamExt};

use crate::senders::traits::{EventStream, Sender};
use crate::utility;

#[derive(Clone)]
pub struct ZmqSender {
    ctx: tmq::Context,
    pipeline_address: String,
    publish_address: String,
}

impl ZmqSender {
    pub fn new() -> Self {
        let publish_address = utility::get_env_variable("ZMQ_PUBLISH_ADDRESS");
        let pipeline_address = utility::get_env_variable("ZMQ_PIPELINE_ADDRESS");
        Self {
            ctx: tmq::Context::new(),
            pipeline_address,
            publish_address,
        }
    }

    fn connect(&self) -> (tmq::publish::Publish, tmq::push::Push) {
        // let curve_server = utility::get_env_variable("ZMQ_CURVE_SERVER")
        //     .expect("Missing ZMQ_CURVE_SERVER env variable");
        let publish_socket = tmq::publish::publish(&self.ctx)
            .bind(&self.publish_address)
            .unwrap_or_else(|exc| {
                panic!(
                    "Failed to connect to ZMQ publish queue with provided path: {} due to {}",
                    &self.publish_address, exc
                )
            });
        let push_socket = tmq::push::push(&self.ctx)
            .bind(&self.pipeline_address)
            .unwrap_or_else(|exc| {
                panic!(
                    "Failed to connect to ZMQ pipeline queue with provided address: {} due to {}",
                    &self.pipeline_address, exc
                )
            });
        // .set_curve_server(&curve_server)
        // set_backlog
        (publish_socket, push_socket)
    }
}

#[async_trait]
impl Sender for ZmqSender {
    async fn consume_all(&self, mut stream: Box<EventStream>) {
        let (mut publish_socket, mut push_socket) = self.connect();
        loop {
            let (shard_id, event_name, payload) = match stream.next().await {
                Some(event) => event,
                None => return,
            };
            // TODO: error handling
            let shard_id = shard_id.to_string();
            let topic = format!("{}:{}", event_name, shard_id);
            // TODO: should we also try the other before returning either error?
            // TODO: handle pin better
            publish_socket
                .start_send_unpin(vec![topic.as_bytes(), payload.as_bytes()])
                .unwrap();
            push_socket
                .start_send_unpin(vec![shard_id.as_bytes(), event_name.as_bytes(), payload.as_bytes()])
                .unwrap();
        }
    }
}
