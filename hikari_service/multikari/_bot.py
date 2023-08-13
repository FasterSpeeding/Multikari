# -*- coding: utf-8 -*-
# cython: language_level=3
# BSD 3-Clause License
#
# Copyright (c) 2021-2023 Faster Speeding
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

__all__ = ["MQBot"]

import asyncio
import datetime
import logging
import math
import typing
import warnings
from concurrent import futures

import hikari
import hikari_orchestrator
from hikari.impl import event_factory  # TODO: this needs to be exported top-level

from . import _event_manager  # pyright: ignore[reportPrivateUsage]
from . import _receivers  # pyright: ignore[reportPrivateUsage]

if typing.TYPE_CHECKING:
    from collections import abc as collections

    from hikari.api import event_manager as event_manager_api
    from typing_extensions import Self

    _EventT = typing.TypeVar("_EventT", bound=hikari.Event)


class MQBot(
    hikari.RESTAware,
    hikari.Runnable,
    hikari.ShardAware,
    hikari.EventFactoryAware,
    hikari.EventManagerAware,
    hikari.api.EventManager,
):
    __slots__ = (
        "_entity_factory",
        "_event_factory",
        "_event_manager",
        "_executor",
        "_http_settings",
        "_intents",
        "_is_alive",
        "_is_closing",
        "_join_event",
        "_me",
        "_orchestrator",
        "_proxy_settings",
        "_receiver",
        "_rest",
        "_voice",
    )

    def __init__(
        self,
        receiver: _receivers.abc.AbstractReceiver,
        manager_url: str,
        token: str,
        /,
        *,
        ca_cert: bytes | None = None,
        http_settings: typing.Optional[hikari.impl.HTTPSettings] = None,
        log_level: typing.Union[str, int, None] = logging.INFO,
        max_rate_limit: float = 300.0,
        max_retries: int = 3,
        proxy_settings: typing.Optional[hikari.impl.ProxySettings] = None,
        discord_url: typing.Optional[str] = None,
    ) -> None:
        if log_level is not None and not logging.root.handlers:
            logging.basicConfig(
                level=log_level,
                format="%(levelname)-1.1s %(asctime)23.23s %(name)s: %(message)s",
            )

            warnings.simplefilter("default", DeprecationWarning)
            logging.captureWarnings(True)

        # TODO: logging stuff?
        self._intents = hikari.Intents.NONE
        self._is_alive = False
        self._is_closing = False
        self._me: typing.Optional[hikari.OwnUser] = None
        self._orchestrator = hikari_orchestrator.Client(token, manager_url, ca_cert=ca_cert)
        self._receiver = receiver

        self._http_settings = http_settings or hikari.impl.HTTPSettings()
        self._proxy_settings = proxy_settings or hikari.impl.ProxySettings()

        self._executor: typing.Optional[futures.Executor] = None

        self._entity_factory = hikari.impl.EntityFactoryImpl(self)
        self._event_factory = event_factory.EventFactoryImpl(self)
        self._event_manager = _event_manager.EventManager(self._receiver, self._event_factory, hikari.Intents.ALL)
        self._join_event: typing.Optional[asyncio.Event] = None
        self._rest = hikari.impl.RESTClientImpl(
            cache=None,
            entity_factory=self._entity_factory,
            executor=self._executor,
            http_settings=self._http_settings,
            max_rate_limit=max_rate_limit,
            max_retries=max_retries,
            proxy_settings=self._proxy_settings,
            token=token,
            token_type=hikari.TokenType.BOT,
            rest_url=discord_url,
        )
        self._voice = hikari.impl.VoiceComponentImpl(self)

    @classmethod
    def create_zmq(
        cls,
        pipeline_url: str,
        publish_url: str,
        manager_url: str,
        token: str,
        /,
        *,
        ca_cert: bytes | None = None,
        http_settings: typing.Optional[hikari.impl.HTTPSettings] = None,
        log_level: typing.Union[str, int, None] = logging.INFO,
        max_rate_limit: float = 300.0,
        max_retries: int = 3,
        proxy_settings: typing.Optional[hikari.impl.ProxySettings] = None,
        discord_url: typing.Optional[str] = None,
    ) -> Self:
        return cls(
            _receivers.ZmqReceiver(pipeline_url, publish_url),
            manager_url,
            token,
            ca_cert=ca_cert,
            http_settings=http_settings,
            log_level=log_level,
            max_rate_limit=max_rate_limit,
            max_retries=max_retries,
            proxy_settings=proxy_settings,
            discord_url=discord_url,
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
    def executor(self) -> typing.Optional[futures.Executor]:
        return self._executor

    @property
    def http_settings(self) -> hikari.api.HTTPSettings:
        return self._http_settings

    @property
    def intents(self) -> hikari.Intents:
        return self._intents

    @property
    def proxy_settings(self) -> hikari.api.ProxySettings:
        return self._proxy_settings

    @property
    def rest(self) -> hikari.api.RESTClient:
        return self._rest

    # ShardAware

    @property
    def heartbeat_latencies(self) -> collections.Mapping[int, float]:
        return {shard_id: shard.heartbeat_latency for shard_id, shard in self._orchestrator.remote_shards.items()}

    @property
    def heartbeat_latency(self) -> float:
        latancies = [
            shard.heartbeat_latency
            for shard in self._orchestrator.remote_shards.values()
            if not math.isnan(shard.heartbeat_latency)
        ]
        return sum(latancies) / len(latancies) if latancies else float("nan")

    @property
    def shards(self) -> collections.Mapping[int, hikari.api.GatewayShard]:
        return self._orchestrator.remote_shards

    @property
    def shard_count(self) -> int:
        return len(self._orchestrator.remote_shards)

    @property
    def voice(self) -> hikari.api.VoiceComponent:
        return self._voice

    def get_me(self) -> typing.Optional[hikari.OwnUser]:
        return self._me

    async def update_presence(
        self,
        *,
        status: hikari.UndefinedOr[hikari.Status] = hikari.UNDEFINED,
        idle_since: hikari.UndefinedNoneOr[datetime.datetime] = hikari.UNDEFINED,
        activity: hikari.UndefinedNoneOr[hikari.Activity] = hikari.UNDEFINED,
        afk: hikari.UndefinedOr[bool] = hikari.UNDEFINED,
    ) -> None:
        await self._orchestrator.update_presence(status=status, idle_since=idle_since, activity=activity, afk=afk)

    async def update_voice_state(
        self,
        guild: hikari.SnowflakeishOr[hikari.PartialGuild],
        channel: typing.Optional[hikari.SnowflakeishOr[hikari.GuildVoiceChannel]],
        *,
        self_mute: hikari.UndefinedOr[bool] = hikari.UNDEFINED,
        self_deaf: hikari.UndefinedOr[bool] = hikari.UNDEFINED,
    ) -> None:
        await self._orchestrator.update_voice_state(guild, channel, self_mute=self_mute, self_deaf=self_deaf)

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
        await self._orchestrator.request_guild_members(
            guild, include_presences=include_presences, query=query, limit=limit, users=users, nonce=nonce
        )

    #  Runnable

    @property
    def is_alive(self) -> bool:
        return self._is_alive

    async def close(self) -> None:
        if not self._is_alive:
            raise RuntimeError("Cannot close a bot that is not alive.")

        if self._is_closing:
            return await self.join()

        self._is_closing = True
        await self._event_manager.dispatch(self._event_factory.deserialize_stopping_event())
        await self._receiver.disconnect()
        await self._voice.close()
        await self._event_manager.dispatch(self._event_factory.deserialize_stopped_event())
        await self._orchestrator.stop()
        await self._rest.close()
        self._is_alive = False
        self._is_closing = False
        if self._join_event:
            self._join_event.set()

    async def join(self) -> None:
        if not self._is_alive:
            raise RuntimeError("Bot is not running")

        if not self._join_event:
            self._join_event = asyncio.Event()

        await self._join_event.wait()

    def run(self) -> None:
        if self._is_alive:
            raise RuntimeError("Bot is already running")

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(self.start())
        loop.run_until_complete(self.join())

    async def start(self) -> None:
        if self._is_alive:
            raise RuntimeError("Bot is already running")

        self._is_alive = True
        self._rest.start()
        self._voice.start()
        await self._orchestrator.start()
        await self._event_manager.dispatch(self._event_factory.deserialize_starting_event())
        await self._receiver.connect(self._on_pipeline, self._on_subbed)
        await self._event_manager.dispatch(self._event_factory.deserialize_started_event())

    def _on_pipeline(self, shard_id: int, event_name: str, payload: bytes, /) -> None:
        shard = self._orchestrator.remote_shards[shard_id]
        self._event_manager.consume_pipeline_event(event_name, shard, payload)

    def _on_subbed(self, shard_id: int, event_name: str, payload: bytes, /) -> None:
        shard = self._orchestrator.remote_shards[shard_id]
        self._event_manager.consume_subbed_event(event_name, shard, payload)

    # hikari.api.EventManager

    def consume_raw_event(
        self, event_name: str, shard: hikari.api.GatewayShard, payload: collections.Mapping[str, typing.Any]
    ) -> None:
        return self._event_manager.consume_raw_event(event_name, shard, payload)

    def dispatch(self, event: hikari.Event) -> asyncio.Future[typing.Any]:
        return self._event_manager.dispatch(event)

    def subscribe(self, event_type: type[typing.Any], callback: event_manager_api.CallbackT[typing.Any]) -> None:
        return self._event_manager.subscribe(event_type, callback)

    def unsubscribe(self, event_type: type[typing.Any], callback: event_manager_api.CallbackT[typing.Any]) -> None:
        return self._event_manager.unsubscribe(event_type, callback)

    def get_listeners(
        self,
        event_type: type[_EventT],
        /,
        *,
        polymorphic: bool = True,
    ) -> collections.Collection[event_manager_api.CallbackT[_EventT]]:
        return self._event_manager.get_listeners(event_type, polymorphic=polymorphic)

    def listen(
        self,
        *event_types: typing.Type[_EventT],
    ) -> collections.Callable[[event_manager_api.CallbackT[_EventT]], event_manager_api.CallbackT[_EventT],]:
        return self._event_manager.listen(*event_types)

    def stream(
        self,
        event_type: type[_EventT],
        /,
        timeout: typing.Union[float, int, None],
        limit: typing.Optional[int] = None,
    ) -> event_manager_api.EventStream[_EventT]:
        return self._event_manager.stream(event_type, timeout=timeout, limit=limit)

    def wait_for(
        self,
        event_type: type[_EventT],
        /,
        timeout: typing.Union[float, int, None],
        predicate: typing.Optional[event_manager_api.PredicateT[_EventT]] = None,
    ) -> collections.Coroutine[typing.Any, typing.Any, _EventT]:
        return self._event_manager.wait_for(event_type, timeout=timeout, predicate=predicate)
