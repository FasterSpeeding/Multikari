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

__all__: typing.Sequence[str] = []

import asyncio
import logging
import os
import typing
import weakref
from concurrent import futures

from hikari.events import lifetime_events

from . import models
from . import utilities

if typing.TYPE_CHECKING:
    from multiprocessing import connection

    from hikari import traits

_ValueT = typing.TypeVar("_ValueT")


class Client(models.SlaveClientProto):
    __slots__: typing.Sequence[str] = ("_close_event", "_connection", "_future", "_logger", "_message_futures")

    def __init__(self, conn: connection.Connection) -> None:
        self._close_event = asyncio.Event()
        self._connection = conn
        self._future: typing.Optional[asyncio.Future[None]] = None
        self._kill_event = asyncio.Event()
        self._logger = logging.getLogger(f"hikari.multikari.{os.getpid()}")
        self._message_futures: weakref.WeakValueDictionary[
            bytes, asyncio.Future[models.BaseMessage]
        ] = weakref.WeakValueDictionary()

    @property
    def is_alive(self) -> bool:
        return self._future is not None

    def close(self) -> None:
        self._close_event.set()

    async def join(self) -> None:
        if not self._future:
            raise RuntimeError("Cannot join a client that hasn't started")

        await self._future

    async def _keep_alive(self, bot: traits.BotAware) -> None:
        close_event = asyncio.create_task(self._close_event.wait())
        conn_event = utilities.Event()
        conn_future: typing.Optional[futures.Future[typing.Any]] = None
        conn_task: typing.Optional[asyncio.Future[typing.Any]] = None
        join_task = asyncio.create_task(bot.join())

        try:
            with futures.ThreadPoolExecutor(1) as thread_pool:
                conn_event.clear()
                conn_future = thread_pool.submit(utilities.poll_recv, self._connection, conn_event)
                conn_task = asyncio.wrap_future(conn_future)

                while True:
                    current_futures = (join_task, conn_task, close_event)
                    done, pending = await asyncio.wait(current_futures, return_when=asyncio.FIRST_COMPLETED)

                    if close_event in done or join_task in done:
                        # TODO: going away message?
                        break

                    message = await conn_task
                    if not isinstance(message, models.BaseMessage):
                        self._logger.warning(
                            "Ignoring invalid message, expected a BaseMessage but got %s", type(message)
                        )

                    else:
                        if message_future := self._message_futures.pop(message.nonce, None):
                            message_future.set_result(message)

                        if isinstance(message, models.CloseMessage):
                            self._logger.info("Process %r going away", os.getpid())
                            break

                        else:
                            self._logger.warning("Ignoring unexpected message type %s", type(message))

                    conn_future = thread_pool.submit(utilities.poll_recv, self._connection, conn_event)
                    conn_task = asyncio.wrap_future(conn_future)

        finally:
            close_event.cancel()
            conn_event.set()
            join_task.cancel()
            if bot.is_alive:
                await bot.close()

            if conn_future is not None:
                conn_future.cancel()

            if conn_task is not None:
                conn_task.cancel()

            self._logger.info("Process %r going away", os.getpid())
            raise

    def run(self, bot: traits.BotAware, shard_count: int, shard_ids: typing.AbstractSet[int]) -> None:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(self.start(bot, shard_count, shard_ids))
        loop.run_until_complete(self.join())

    async def start(self, bot: traits.BotAware, shard_count: int, shard_ids: typing.AbstractSet[int]) -> None:
        if self._future:
            raise RuntimeError("Cannot start a client that's already running")

        if bot.is_alive:
            raise RuntimeError("Cannot start with a bot that's already running")

        @bot.event_manager.listen(lifetime_events.StartedEvent)
        async def on_started(_: lifetime_events.StartedEvent) -> None:
            self._connection.send(models.StartedMessage())
            bot.event_manager.unsubscribe(lifetime_events.StartedEvent, on_started)

        await bot.start(shard_count=shard_count, shard_ids=shard_ids)
        self._close_event.clear()
        self._future = asyncio.create_task(self._keep_alive(bot))

    def send(self, message: models.BaseMessage, /) -> asyncio.Future[models.BaseMessage]:
        self.send_no_wait(message)
        future: asyncio.Future[models.BaseMessage] = asyncio.Future()
        self._message_futures[message.nonce] = future
        return future

    def send_no_wait(self, message: models.BaseMessage, /) -> None:
        if not self._future:
            raise RuntimeError("Cannot send on a client that isn't running")

        self._connection.send(message)


# TODO: support a string for the builder
def process_main(
    builder: models.BotBuilderProto,
    conn: connection.Connection,
    shard_count: int,
    shard_ids: typing.AbstractSet[int],
) -> None:
    try:
        cli = Client(conn)
        cli.run(builder(cli), shard_count=shard_count, shard_ids=shard_ids)

    # We only want to see these on the master process otherwise this gets really spammy
    except KeyboardInterrupt:
        pass
