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
#[cfg(feature = "dto")]
pub mod dto;
#[cfg(feature = "middleware")]
pub mod middleware;

use std::str::FromStr;

pub fn load_env() -> dotenv::Result<std::path::PathBuf> {
    dotenv::dotenv()
}

pub fn try_get_env_variable(key: &str) -> Option<String> {
    dotenv::var(key).or_else(|_| std::env::var(key)).ok()
}

pub fn get_env_variable(key: &str) -> String {
    try_get_env_variable(key).unwrap_or_else(|| panic!("Environment variable {} not found", key))
}

pub fn strip_url<S: Into<String>>(url: S) -> String {
    url.into().replacen("http://", "", 1).replacen("https://", "", 1)
}

pub fn unstrip_url<S: Into<String>>(url: S) -> String {
    let url = url.into();
    if !url.starts_with("http://") && !url.starts_with("https://") {
        format!("https://{}", url)
    } else {
        url
    }
}

pub fn setup_logging() {
    let level = match try_get_env_variable("LOG_LEVEL").map(|v| log::LevelFilter::from_str(&v)) {
        Some(Err(..)) => {
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

pub fn setup() {
    let dotenv_result = load_env();
    setup_logging();

    if let Err(error) = dotenv_result {
        log::info!("Couldn't load .env file: {}", error);
    }
}
