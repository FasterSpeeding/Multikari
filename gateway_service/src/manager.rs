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
use actix_web::http::header;
use shared::dto;

pub struct Client {
    authorization: String,
    client: reqwest::Client,
    url: String,
}

impl Client {
    pub fn new(url: &str, token: &str) -> Self {
        Self {
            authorization: format!("Basic {}", base64::encode(&format!("__token__:{}", token))),
            client: reqwest::Client::new(),
            url: url.to_owned(),
        }
    }

    fn start_request(&self, endpoint: &str, method: reqwest::Method) -> reqwest::RequestBuilder {
        self.client
            .request(method, &format!("{}/{}", self.url, endpoint))
            .header(header::AUTHORIZATION, &self.authorization)
    }

    async fn get_shard(&self, shard_id: u64) -> Result<dto::Shard, reqwest::Error> {
        self.start_request(&format!("shards/{}", shard_id), reqwest::Method::GET)
            .send()
            .await?
            .json()
            .await
    }
}
