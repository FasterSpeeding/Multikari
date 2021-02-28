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

__all__: typing.Sequence[str] = ["Puppeteer"]

import asyncio
import importlib.util
import logging
import math
import multiprocessing
import typing
from multiprocessing import connection
from multiprocessing import pool

from . import models
from . import slave
from . import utilities

if typing.TYPE_CHECKING:
    import pathlib

    from hikari import sessions


_LOGGER = logging.getLogger("hikari.multikari")
_ValueT = typing.TypeVar("_ValueT")


async def _fetch_gateway_bot(token: str) -> sessions.GatewayBot:
    from hikari.impl import rest

    async with rest.RESTApp().acquire(token, token_type="Bot") as rest_client:
        return await rest_client.fetch_gateway_bot()


class _FailedStart(Exception):
    __slots__: typing.Sequence[str] = ()

    __cause__: Exception


class Puppeteer:
    __slots__: typing.Sequence[str] = ("builder", "_connections", "_lock", "_pool", "_results", "_task", "_token")

    def __init__(self, builder: models.BotBuilderProto, token: str, /) -> None:
        self.builder = builder
        self._connections: typing.List[connection.Connection] = []
        self._lock = asyncio.Lock()
        self._pool: typing.Optional[pool.Pool] = None
        self._results: typing.List[pool.AsyncResult[None]] = []
        self._task: typing.Optional[asyncio.Task[None]] = None
        self._token = token

    @property
    def is_alive(self) -> bool:
        return self._pool is not None

    async def _handle_results(self) -> None:
        tasks = [asyncio.get_event_loop().run_in_executor(None, result.get) for result in self._results]
        _, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

        for task in pending:
            task.cancel()

        await self.close()
        return

    @classmethod
    def from_package(cls, package: str, attribute: str, token: str, /) -> Puppeteer:
        builder_module = importlib.import_module(package)
        builder = getattr(builder_module, attribute)
        assert callable(builder)
        return Puppeteer(builder, token)

    @classmethod
    def from_path(cls, path: pathlib.Path, attribute: str, token: str, /) -> Puppeteer:
        spec = importlib.util.spec_from_file_location(path.name, str(path.absolute()))
        if not spec:
            raise RuntimeError(f"Module not found at path {path}")

        builder_module = importlib.util.module_from_spec(spec)
        # The typeshed is wrong
        spec.loader.exec_module(builder_module)  # type: ignore[union-attr]
        builder = getattr(builder_module, attribute, None)

        if not builder:
            raise RuntimeError(f"Builder not found at {path}:{attribute}")

        if not callable(builder):
            raise RuntimeError(f"Builder found at {path}:{attribute} is not callable")

        return Puppeteer(builder, token)

    async def close(self, *, timeout: int = 60) -> None:
        async with self._lock:
            if not self._pool:
                raise RuntimeError("Cannot close an instance that isn't running")

            for conn in self._connections:
                conn.send({"type": models.MessageType.CLOSE})

            # Try to wait for the child processes to end smoothly before slamming the line on them.
            tasks = [asyncio.get_event_loop().run_in_executor(None, result.get) for result in self._results]
            _, pending = await asyncio.wait(tasks, timeout=timeout)

            for task in pending:
                task.cancel()

            self._pool.terminate()
            self._pool = None
            self._task = None

    async def join(self) -> None:
        if not self._task:
            raise RuntimeError("Cannot wait for a client that's never started to join")

        await self._task

    def run(
        self,
        *,
        process_size: int = 1,
        shard_count: typing.Optional[int] = None,
        shard_ids: typing.Optional[typing.AbstractSet[int]] = None,
    ) -> None:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(self.spawn(process_size=process_size, shard_count=shard_count, shard_ids=shard_ids))
        assert self._task is not None, "this should've been set by self.spawn"
        loop.run_until_complete(self.join())
        # This just gets stuck after returning/raising before reaching wherever this is being called from on Windows and
        # I don't think there's much I can do about that so...

    async def spawn(
        self,
        *,
        process_size: int = 1,
        shard_count: typing.Optional[int] = None,
        shard_ids: typing.Optional[typing.AbstractSet[int]] = None,
    ) -> None:
        async with self._lock:
            if self._pool:
                raise RuntimeError("Cannot spawn an instance that's already running")

            if shard_ids and not shard_count:
                raise ValueError("shard_count must be passed when shard_ids is passed")

            elif shard_count and not shard_ids:
                raise ValueError("shard_ids must be passed when shard_count is passed")

            elif not shard_count and not shard_ids:
                gateway_bot = await _fetch_gateway_bot(self._token)
                shard_count = gateway_bot.shard_count
                shard_ids = set(range(shard_count))

            assert shard_ids is not None
            assert shard_count is not None

            if len(shard_ids) > shard_count:
                raise ValueError("shard_count must be greater than or equal to the length of shard_ids")

            if process_size <= 0:
                raise ValueError("process_size must be greater than 1")

            loop = asyncio.get_event_loop()

            self._pool = pool.Pool(math.ceil(len(shard_ids) / process_size))
            try:
                for chunk in utilities.chunk_values(shard_ids, process_size):
                    our_channel, their_channel = multiprocessing.Pipe()
                    self._connections.append(our_channel)
                    receive_task = loop.run_in_executor(None, utilities.soft_recv, our_channel.recv)
                    assert isinstance(receive_task, asyncio.Future), "docs say this is a future"

                    _LOGGER.info("Starting shards ")
                    result = self._pool.apply_async(
                        slave.process_main, (self.builder, their_channel, shard_count, chunk)
                    )
                    self._results.append(result)
                    result_task = loop.run_in_executor(None, result.get)
                    assert isinstance(result_task, asyncio.Future), "docs say this is a future"

                    done, pending = await asyncio.wait((receive_task, result_task), return_when=asyncio.FIRST_COMPLETED)

                    if result_task in done:
                        receive_task.cancel()
                        # This should always raise
                        await result_task

                    result_task.cancel()
                    message = await receive_task
                    message_type = message.get("type")

                    if message_type is models.MessageType.CLOSE:
                        raise _FailedStart from RuntimeError("Startup interrupted")

                    if message_type is not models.MessageType.STARTED:
                        raise _FailedStart from ValueError(f"Received invalid message type {message_type}")

                    # TODO: we could probably work out if we need to do this each iteration with some maths
                    # This accounts for max concurrency
                    await asyncio.sleep(5)

            except Exception as exc:
                await self.close()
                if isinstance(exc, _FailedStart):
                    raise exc.__cause__
                raise

            self._task = asyncio.create_task(self._handle_results())
