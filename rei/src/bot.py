# -*- coding: utf-8 -*-
# cython: language_level=3
# BSD 3-Clause License
#
# Copyright (c) 2021, Faster Speeding
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# * Redistributions of source code must retain the above copyright notice, this
#   list of conditions and the following disclaimer.
#
# * Redistributions in binary form must reproduce the above copyright notice,
#   this list of conditions and the following disclaimer in the documentation
#   and/or other materials provided with the distribution.
#
# * Neither the name of the copyright holder nor the names of its
#   contributors may be used to endorse or promote products derived from
#   this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
# FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
# SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
# OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
from __future__ import annotations

__all__ = []

import datetime
import typing
from concurrent import futures

import hikari
import hikari.config
import hikari.impl.event_factory
import hikari.traits

from . import receiver


class MQBot(
    hikari.traits.RESTAware,
    hikari.traits.Runnable,
    hikari.traits.ShardAware,
    hikari.traits.EventFactoryAware,
    hikari.traits.EventManagerAware,
):
    __slots__ = ("_entity_factory", "_event_factory", "_event_manager", "_executor", "_rest")

    def __init__(self, receiver: receiver.AbstractReceiver, /, token: str) -> None:
        self._entity_factory = hikari.impl.EntityFactoryImpl(self)
        self._event_factory = hikari.impl.event_factory.EventFactoryImpl(self)
        self._event_manager = hikari.impl.EventManagerImpl(self, intents=hikari.Intents.ALL)
        self._executor: typing.Optional[futures.Executor] = None
        self._rest = hikari.impl.RESTClientImpl(
            cache=None,
            entity_factory=self._entity_factory,
            executor=self._executor,
            http_settings=...,
            max_rate_limit=...,
            max_retries=...,
            proxy_settings=...,
            token=token,
            token_type=hikari.TokenType.BOT,
            rest_url=None,
        )

    @property
    def entity_factory(self) -> hikari.api.EntityFactory:
        return self._entity_factory

    @property
    def event_factory(self) -> hikari.api.EventFactory:
        return self._event_factory

    @property
    def event_manager(self) -> hikari.api.EventManager:
        return self._event_manager

    @property
    def executor(self) -> hikari.api.Executor:
        return self._executor

    @property
    def http_settings(self) -> hikari.config.HTTPSettings:
        return super().http_settings

    @property
    def proxy_settings(self) -> hikari.config.ProxySettings:
        return super().proxy_settings

    @property
    def rest(self) -> hikari.api.RESTClient:
        return self._rest

    # ShardAware

    @property
    def heartbeat_latencies(self) -> typing.Mapping[int, float]:
        ...

    @property
    def heartbeat_latency(self) -> float:
        ...

    @property
    def shards(self) -> typing.Mapping[int, hikari.api.GatewayShard]:
        ...

    @property
    def shard_count(self) -> int:
        ...

    def get_me(self) -> typing.Optional[hikari.OwnUser]:
        return None

    async def update_presence(
        self,
        *,
        status: hikari.UndefinedOr[hikari.Status] = hikari.UNDEFINED,
        idle_since: hikari.UndefinedNoneOr[datetime.datetime] = hikari.UNDEFINED,
        activity: hikari.UndefinedNoneOr[hikari.Activity] = hikari.UNDEFINED,
        afk: hikari.UndefinedOr[bool] = hikari.UNDEFINED,
    ) -> None:
        ...

    async def update_voice_state(
        self,
        guild: hikari.SnowflakeishOr[hikari.PartialGuild],
        channel: typing.Optional[hikari.SnowflakeishOr[hikari.GuildVoiceChannel]],
        *,
        self_mute: hikari.UndefinedOr[bool] = hikari.UNDEFINED,
        self_deaf: hikari.UndefinedOr[bool] = hikari.UNDEFINED,
    ) -> None:
        ...

    async def request_guild_members(
        self,
        guild: hikari.SnowflakeishOr[hikari.PartialGuild],
        *,
        include_presences: hikari.UndefinedOr[bool] = hikari.UNDEFINED,
        query: str = "",
        limit: int = 0,
        users: hikari.UndefinedOr[hikari.SnowflakeishSequence[hikari.User]] = hikari.UNDEFINED,
        nonce: hikari.UndefinedOr[str] = hikari.UNDEFINED,
    ) -> None:
        ...

    #  Runnable

    @property
    def is_alive(self) -> bool:
        ...

    async def close(self) -> None:
        ...

    async def join(self) -> None:
        ...

    def run(self) -> None:
        ...

    async def start(self) -> None:
        ...
