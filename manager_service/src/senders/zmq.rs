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
use std::marker::Unpin;
use std::pin::Pin;
use std::sync::Arc;
use std::task::{Context, Poll};

use async_trait::async_trait;
use futures_util::{Sink, SinkExt, Stream};
use tmq::{Multipart, TmqError};
use tokio::sync::Mutex;

use crate::senders::traits::{Event, EventStream, Sender};


struct JoinedSockets {
    publish_socket: tmq::publish::Publish,
    push_socket: tmq::push::Push,
}

impl JoinedSockets {
    fn new(publish_socket: tmq::publish::Publish, push_socket: tmq::push::Push) -> Self {
        Self {
            push_socket,
            publish_socket,
        }
    }
}

impl Sink<Event> for JoinedSockets {
    type Error = TmqError;

    fn poll_ready(mut self: Pin<&mut Self>, ctx: &mut Context<'_>) -> Poll<Result<(), Self::Error>> {
        let result = Pin::new(&mut self.publish_socket as &mut (dyn Sink<Multipart, Error = TmqError> + Unpin))
            .poll_ready(ctx)?;

        if result == Poll::Pending {
            return Poll::Pending;
        }

        Pin::new(&mut self.push_socket as &mut (dyn Sink<Multipart, Error = TmqError> + Unpin)).poll_ready(ctx)
    }

    fn start_send(mut self: Pin<&mut Self>, item: Event) -> Result<(), Self::Error> {
        let (shard_id, event_name, payload) = item;
        let shard_id = shard_id.to_string();
        let topic = format!("{}:{}", event_name, shard_id);
        // TODO: should we also try the other before returning either error?
        Pin::new(&mut self.publish_socket).start_send(vec![topic.as_bytes(), &payload])?;
        Pin::new(&mut self.push_socket).start_send(vec![shard_id.as_bytes(), event_name.as_bytes(), &payload])
    }

    fn poll_flush(mut self: Pin<&mut Self>, ctx: &mut Context<'_>) -> Poll<Result<(), Self::Error>> {
        let result = Pin::new(&mut self.publish_socket as &mut (dyn Sink<Multipart, Error = TmqError> + Unpin))
            .poll_flush(ctx)?;

        if result == Poll::Pending {
            return Poll::Pending;
        }

        Pin::new(&mut self.push_socket as &mut (dyn Sink<Multipart, Error = TmqError> + Unpin)).poll_flush(ctx)
    }

    fn poll_close(mut self: Pin<&mut Self>, ctx: &mut Context<'_>) -> Poll<Result<(), Self::Error>> {
        let result = Pin::new(&mut self.publish_socket as &mut (dyn Sink<Multipart, Error = TmqError> + Unpin))
            .poll_close(ctx)?;

        if result == Poll::Pending {
            return Poll::Pending;
        }

        Pin::new(&mut self.push_socket as &mut (dyn Sink<Multipart, Error = TmqError> + Unpin)).poll_close(ctx)
    }
}


pub struct ZmqSender {
    sockets: Arc<Mutex<JoinedSockets>>,
}

impl ZmqSender {
    pub async fn new() -> Self {
        let publish_address = shared::get_env_variable("ZMQ_PUBLISH_ADDRESS");
        let pipeline_address = shared::get_env_variable("ZMQ_PIPELINE_ADDRESS");
        // let curve_server = shared::get_env_variable("ZMQ_CURVE_SERVER")
        //     .expect("Missing ZMQ_CURVE_SERVER env variable");

        let ctx = tmq::Context::new();
        let publish_socket = tmq::publish::publish(&ctx)
            .bind(&publish_address)
            .unwrap_or_else(|exc| {
                panic!(
                    "Failed to connect to ZMQ publish queue with provided path: {} due to {}",
                    &publish_address, exc
                )
            });
        let push_socket = tmq::push::push(&ctx).bind(&pipeline_address).unwrap_or_else(|exc| {
            panic!(
                "Failed to connect to ZMQ pipeline queue with provided address: {} due to {}",
                &pipeline_address, exc
            )
        });
        // .set_curve_server(&curve_server)
        // set_backlog

        Self {
            sockets: Arc::new(Mutex::new(JoinedSockets::new(publish_socket, push_socket))),
        }
    }
}

struct TryAdapter {
    inner: Box<EventStream>,
}

impl TryAdapter {
    fn new(inner: Box<EventStream>) -> Self {
        Self { inner }
    }
}

impl Stream for TryAdapter {
    type Item = Result<Event, TmqError>;

    fn poll_next(mut self: Pin<&mut Self>, ctx: &mut Context<'_>) -> Poll<Option<Self::Item>> {
        Pin::new(&mut self.inner).poll_next(ctx).map(|v| v.map(Ok))
    }

    fn size_hint(&self) -> (usize, Option<usize>) {
        self.inner.size_hint()
    }
}


#[async_trait]
impl Sender for ZmqSender {
    async fn consume_all(&self, stream: Box<EventStream>) {
        // TODO: error handling
        self.sockets
            .lock()
            .await
            .send_all(&mut TryAdapter::new(stream))
            .await
            .unwrap();
    }
}
