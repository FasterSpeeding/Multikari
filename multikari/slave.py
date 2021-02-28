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
import sys
import typing
import uuid
from concurrent import futures

from hikari.events import lifetime_events

from . import models
from . import utilities

if typing.TYPE_CHECKING:
    from multiprocessing import connection

_ValueT = typing.TypeVar("_ValueT")


async def async_main(
    builder: models.BotBuilderProto, conn: connection.Connection, shard_count: int, shard_ids: typing.AbstractSet[int]
) -> None:
    logger = logging.getLogger(f"hikari.multikari.{os.getpid()}")
    thread_pool = futures.ThreadPoolExecutor(1)
    bot = builder()

    @bot.event_manager.listen(lifetime_events.StartedEvent)
    async def on_started(_: lifetime_events.StartedEvent) -> None:
        conn.send(models.StartedMessage(nonce=uuid.uuid4().bytes))
        bot.event_manager.unsubscribe(lifetime_events.StartedEvent, on_started)

    await bot.start(shard_count=shard_count, shard_ids=shard_ids)

    while True:
        try:
            join_task = asyncio.create_task(bot.join())
            conn_future = thread_pool.submit(utilities.soft_recv, conn.recv)
            conn_task = asyncio.wrap_future(conn_future)

            done, pending = await asyncio.wait((join_task, conn_task), return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()

            if join_task in done:
                conn_future.cancel()
                # TODO: going away message?
                break

            message = await conn_task
            # This check is technically unnecessary thus we only do it as a debugging step.
            if __debug__ and not isinstance(message, models.BaseMessage):
                logger.warning("Ignoring invalid message, expected a BaseMessage but got %s", type(message))

            elif isinstance(message, models.CloseMessage):
                if bot.is_alive:
                    await bot.close()

                logger.info("Process %r going away", os.getpid())
                return

            else:
                logger.warning("Ignoring unknown message type %s", type(message))

        except KeyboardInterrupt:
            if bot.is_alive:
                await bot.close()

            if sys.version_info.minor >= 9:
                thread_pool.shutdown(wait=False, cancel_futures=True)

            else:
                thread_pool.shutdown(wait=False)

            logger.info("Process %r going away", os.getpid())
            raise


# TODO: support a string for the builder
def process_main(
    builder: models.BotBuilderProto,
    conn: connection.Connection,
    shard_count: int,
    shard_ids: typing.AbstractSet[int],
) -> None:
    try:
        asyncio.run(async_main(builder, conn, shard_count, shard_ids))

    # We only want to see these on the master process otherwise this gets really spammy
    except KeyboardInterrupt:
        pass
