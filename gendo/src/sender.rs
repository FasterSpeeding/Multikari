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
use async_trait::async_trait;
use futures::SinkExt;

#[async_trait]
pub trait Sender {
    async fn consume_event(&self, shard_id: u64, event_name: &str, event: &str);
}

pub struct ZmqSender {
    ctx:            tmq::Context,
    push_socket:    std::sync::Arc<tokio::sync::Mutex<tmq::push::Push>>,
    publish_socket: std::sync::Arc<tokio::sync::Mutex<tmq::publish::Publish>>,
}

impl ZmqSender {
    pub async fn build() -> Self {
        let pipeline_address =
            shared::get_env_variable("ZMQ_PIPELINE_ADDRESS").expect("Missing ZMQ_PIPELINE_ADDRESS env variable");
        let publish_address =
            shared::get_env_variable("ZMQ_PUBLISH_ADDRESS").expect("Missing ZMQ_PUBLISH_ADDRESS env variable");
        // let curve_server = shared::get_env_variable("ZMQ_CURVE_SERVER")
        //     .expect("Missing ZMQ_CURVE_SERVER env variable");

        let ctx = tmq::Context::new();
        let push_socket = tmq::push::push(&ctx).bind(&pipeline_address).expect(format!(
            "Failed to connect to ZMQ pipeline queue with provided address: {}",
            &pipeline_address
        ));
        // .set_curve_server(&curve_server)
        // set_backlog

        let publish_socket = tmq::publish::publish(&ctx).bind(&publish_address).expect(format!(
            "Failed to connect to ZMQ publish queue with provided path: {}",
            &publish_address
        ));

        Self {
            ctx,
            push_socket: std::sync::Arc::from(tokio::sync::Mutex::from(push_socket)),
            publish_socket: std::sync::Arc::from(tokio::sync::Mutex::from(publish_socket)),
        }
    }
}

#[async_trait]
impl Sender for ZmqSender {
    async fn consume_event(&self, shard_id: u64, event_name: &str, event: &str) {
        self.push_socket
            .lock()
            .await
            .send(vec![&format!("{}", shard_id) as &str, event_name, event])
            .await
            .unwrap(); // TODO:  error handling

        self.publish_socket
            .lock()
            .await
            .send(vec![&format!("{}:{}", event_name, shard_id) as &str, event])
            .await
            .unwrap();
    }
}
