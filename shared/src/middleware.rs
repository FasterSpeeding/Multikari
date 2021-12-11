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
use std::future::Future;
use std::pin::Pin;

use actix_utils::future::{ready, Ready};
use actix_web::dev::{forward_ready, Service, ServiceRequest, ServiceResponse, Transform};
use actix_web::error::InternalError;
use actix_web::http::{header, StatusCode};
use actix_web::Error;


fn error_early<O>(payload: &'static str, status_code: StatusCode) -> Ready<Result<O, Error>> {
    ready(Err(Error::from(InternalError::new(payload, status_code))))
}

fn bad_token<O>() -> Ready<Result<O, Error>> {
    error_early("Missing or invalid authorization header", StatusCode::UNAUTHORIZED)
}

pub struct TokenAuth {
    token: String,
}

impl TokenAuth {
    pub fn new(token: &str) -> Self {
        let token = base64::encode(format!("__token__:{}", token))
            .trim_end_matches('=')
            .to_string();
        TokenAuth { token }
    }
}

impl<S, B: 'static> Transform<S, ServiceRequest> for TokenAuth
where
    S: Service<ServiceRequest, Response = ServiceResponse<B>, Error = Error>,
    S::Future: 'static,
{
    type Error = Error;
    type Future = Ready<Result<Self::Transform, Self::InitError>>;
    type InitError = ();
    type Response = ServiceResponse<B>;
    type Transform = TokenAuthWrapper<S, B>;

    fn new_transform(&self, service: S) -> Self::Future {
        ready(Ok(TokenAuthWrapper {
            token: self.token.clone(),
            service,
        }))
    }
}

pub struct TokenAuthWrapper<S, B>
where
    S: Service<ServiceRequest, Response = ServiceResponse<B>, Error = actix_web::Error>,
    S::Future: 'static, {
    service: S,
    token:   String,
}


impl<S, B: 'static> Service<ServiceRequest> for TokenAuthWrapper<S, B>
where
    S: Service<ServiceRequest, Response = ServiceResponse<B>, Error = actix_web::Error>,
    S::Future: 'static,
{
    type Error = S::Error;
    type Future = Pin<Box<dyn Future<Output = Result<Self::Response, Self::Error>>>>;
    type Response = S::Response;

    forward_ready!(service);

    fn call(&self, req: ServiceRequest) -> Self::Future {
        let auth = req
            .headers()
            .get(header::AUTHORIZATION)
            .map(|v| v.to_str().ok())
            .flatten()
            .map(|v| v.split_once(' '));

        let (token_type, auth) = match auth {
            Some(Some((token_type, auth))) => (token_type, auth),
            _ => return Box::pin(bad_token::<Self::Response>()),
        };

        if !token_type.eq_ignore_ascii_case("Basic") {
            Box::pin(bad_token::<Self::Response>())
        } else if auth.trim_end_matches('=') == self.token {
            Box::pin(self.service.call(req))
        } else {
            Box::pin(error_early::<Self::Response>("Unknown token", StatusCode::UNAUTHORIZED))
        }
    }
}
