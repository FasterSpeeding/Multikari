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

__all__: typing.Sequence[str] = ["Master"]

import asyncio
import importlib.util
import logging
import math
import multiprocessing
import sys
import time
import typing
from concurrent import futures

from . import models
from . import slave
from . import utilities

if typing.TYPE_CHECKING:
    import pathlib

    from hikari import sessions


_LOGGER = logging.getLogger("hikari.multikari")
_ValueT = typing.TypeVar("_ValueT")
DEFAULT_PROCESS_SIZE: typing.Final[int] = 1
DEFAULT_TIMEOUT: typing.Final[float] = 60.0
TimeoutT = typing.Union[int, float]


async def _fetch_gateway_bot(token: str) -> sessions.GatewayBot:
    from hikari.impl import rest

    async with rest.RESTApp().acquire(token, token_type="Bot") as rest_client:
        return await rest_client.fetch_gateway_bot()


class Master:
    __slots__: typing.Sequence[str] = (
        "builder",
        "_close_event",
        "_connections",
        "_future",
        "_lock",
        "_new_cluster_event",
        "_process_futures",
        "_process_pool",
        "_process_size",
        "_shard_stats",
        "_thread_pool",
        "_token",
    )

    def __init__(
        self,
        builder: models.BotBuilderProto,
        token: str,
        /,
        shard_count: int,
        shard_ids: typing.AbstractSet[int],
        *,
        process_size: int = DEFAULT_PROCESS_SIZE,
    ) -> None:
        if len(shard_ids) > shard_count:
            raise ValueError("shard_count must be greater than or equal to the length of shard_ids")

        if process_size <= 0:
            raise ValueError("process_size must be greater than 1")

        self.builder = builder
        self._close_event = utilities.Event()
        self._connections: typing.Dict[typing.FrozenSet[int], multiprocessing.connection.Connection] = {}
        self._future: typing.Optional[futures.Future[None]] = None
        self._lock = multiprocessing.Lock()
        self._new_cluster_event = (utilities.Event(), multiprocessing.Lock())
        self._process_futures: typing.Dict[futures.Future[None], typing.FrozenSet[int]] = {}
        self._process_pool: typing.Optional[futures.ProcessPoolExecutor] = None
        self._process_size = process_size
        self._shard_stats = (shard_count, shard_ids)
        self._thread_pool: typing.Optional[futures.ThreadPoolExecutor] = None
        self._token = token

    @property
    def is_alive(self) -> bool:
        return self._future is not None

    @staticmethod
    def fetch_shard_stats(token: str, /) -> typing.Tuple[int, typing.AbstractSet[int]]:
        gateway_bot = asyncio.get_event_loop().run_until_complete(_fetch_gateway_bot(token))
        return gateway_bot.shard_count, frozenset(range(gateway_bot.shard_count))

    @classmethod
    def from_package(
        cls,
        package: str,
        attribute: str,
        token: str,
        /,
        shard_count: int,
        shard_ids: typing.AbstractSet[int],
        *,
        process_size: int = DEFAULT_PROCESS_SIZE,
    ) -> Master:
        try:
            builder_module = importlib.import_module(package)

        except ImportError as exc:
            raise RuntimeError(f"Couldn't find package {package!r}") from exc

        builder = getattr(builder_module, attribute, None)
        if builder is None:
            raise RuntimeError(f"Couldn't find builder {package}:{attribute}")

        if not callable(builder):
            raise RuntimeError(f"Builder found at {package}:{attribute} isn't callable")

        return Master(builder, token, shard_count=shard_count, shard_ids=shard_ids, process_size=process_size)

    @classmethod
    def from_path(
        cls,
        path: pathlib.Path,
        attribute: str,
        token: str,
        /,
        shard_count: int,
        shard_ids: typing.AbstractSet[int],
        *,
        process_size: int = DEFAULT_PROCESS_SIZE,
    ) -> Master:
        spec = importlib.util.spec_from_file_location(path.name, str(path.absolute()))
        if not spec:
            raise RuntimeError(f"Module not found at path {path}")

        builder_module = importlib.util.module_from_spec(spec)
        # The typeshed is wrong
        spec.loader.exec_module(builder_module)  # type: ignore[union-attr]

        builder = getattr(builder_module, attribute, None)
        if builder is None:
            raise RuntimeError(f"Builder not found at {path}:{attribute}")

        if not callable(builder):
            raise RuntimeError(f"Builder found at {path}:{attribute} is not callable")

        return Master(builder, token, shard_count=shard_count, shard_ids=shard_ids, process_size=process_size)

    def _keep_alive(self) -> None:
        with self._new_cluster_event[1]:
            process_futures_map = self._process_futures.copy()

        process_futures_set = frozenset(process_futures_map.keys())
        close_future = self._close_event.future()
        connections = self._connections.copy()
        connection_event = utilities.Event()
        connections_future: typing.Optional[
            futures.Future[typing.Optional[typing.Iterable[multiprocessing.connection.Connection]]]
        ] = None
        new_cluster_future: typing.Optional[futures.Future[typing.Any]] = None
        assert self._thread_pool is not None

        try:
            while True:
                if connections_future is None:
                    connection_event.clear()
                    connections_future = self._thread_pool.submit(
                        utilities.poll_connections, connections.values(), connection_event
                    )

                if new_cluster_future is None:
                    new_cluster_future = self._new_cluster_event[0].future()

                current_futures: typing.Sequence[futures.Future[typing.Any]] = (
                    close_future,
                    connections_future,
                    new_cluster_future,
                    *process_futures_set,
                )
                done, _ = futures.wait(current_futures, return_when=futures.FIRST_COMPLETED)

                if close_future in done:
                    connection_event.set()
                    connections_future.cancel()
                    return

                if connections_future in done:
                    passed_connections = connections_future.result()
                    ...  # TODO: stuff
                    connection_event.set()
                    connections_future = None

                # TODO: if this happens we should wait for like 5 seconds to see if like 25% of the clusters come down
                # to guess if it's irrecoverable.
                finished_processes = ()  # TODO this as well lmao

                if new_cluster_future in done:
                    with self._new_cluster_event[1]:
                        process_futures_map = self._process_futures.copy()
                        process_futures_set = frozenset(process_futures_map)
                        connections = self._connections.copy()
                        self._new_cluster_event[0].clear()

                    connections_future = None
                    new_cluster_future = None

        finally:
            connection_event.set()
            close_future.cancel()

            if connections_future:
                connections_future.cancel()

            if new_cluster_future:
                new_cluster_future.cancel()

            self.close()

    def close(self, *, timeout: TimeoutT = DEFAULT_TIMEOUT) -> None:
        with self._lock:
            if not self._future:
                raise RuntimeError("Cannot close an instance that isn't running")

            self.__close(timeout=timeout)

    def __close(self, *, timeout: TimeoutT = DEFAULT_TIMEOUT) -> None:
        self._close_event.set()
        assert self._process_pool is not None
        assert self._thread_pool is not None
        for conn in self._connections.values():
            conn.send(models.CloseMessage())

        # Try to wait for the child processes to end smoothly before slamming the line on them.
        _, pending = futures.wait(self._process_futures.keys(), timeout=timeout)
        for future in pending:
            future.cancel()

        if sys.version_info.minor >= 9:
            self._process_pool.shutdown(wait=False, cancel_futures=True)
            self._thread_pool.shutdown(wait=False, cancel_futures=True)

        else:
            self._process_pool.shutdown(wait=False)
            self._thread_pool.shutdown(wait=False)

        self._process_pool = None
        self._future = None
        self._thread_pool = None

    def join(self) -> None:
        with self._lock:
            if not self._future:
                raise RuntimeError("Cannot wait for a client that's not started to join")

            task = self._future

        task.result()

    def run(self) -> None:
        self.start()
        self.join()

    def start(self) -> None:
        with self._lock:
            if self._future:
                raise RuntimeError("Cannot start an instance that's already running")

            self._close_event.clear()
            self._process_pool = futures.ProcessPoolExecutor(math.ceil(len(self._shard_stats[1]) / self._process_size))
            self._thread_pool = futures.ThreadPoolExecutor(4)
            self._future = self._thread_pool.submit(self._keep_alive)

            close_receive = utilities.Event()
            try:
                for raw_chunk in utilities.chunk_values(self._shard_stats[1], self._process_size):
                    chunk = frozenset(raw_chunk)
                    close_receive.clear()
                    our_channel, their_channel = multiprocessing.Pipe()
                    self._connections[chunk] = our_channel
                    receive_future = self._thread_pool.submit(utilities.poll_recv, our_channel, close_receive)

                    _LOGGER.info("Starting shards")
                    process_future = self._process_pool.submit(
                        slave.process_main, self.builder, their_channel, self._shard_stats[0], chunk
                    )

                    current_futures: typing.Sequence[futures.Future[typing.Any]] = (receive_future, process_future)
                    done, _ = futures.wait(current_futures, return_when=futures.FIRST_COMPLETED)

                    if process_future in done:
                        # This result call is expected to always raise.
                        result = process_future.result()
                        raise RuntimeError(f"Bot instance returned {result} instead of running")

                    message = receive_future.result()
                    if isinstance(message, models.CloseMessage):
                        raise RuntimeError("Startup interrupted")

                    elif not isinstance(message, models.StartedMessage):
                        raise ValueError(f"Expected a startup confirmation but got {type(message)}")

                    with self._new_cluster_event[1]:
                        self._process_futures[process_future] = chunk
                        self._new_cluster_event[0].set()

                    # TODO: we could probably work out if we need to do this each iteration with some maths
                    # This accounts for max concurrency
                    time.sleep(5)

            except BaseException:
                close_receive.set()
                receive_future.cancel()
                self.__close()
                raise
