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

__all__ = ["ZmqReceiver"]

import asyncio
import logging
import typing

from . import abc

if typing.TYPE_CHECKING:
    import types
    from collections import abc as collections

    import zmq
    import zmq.asyncio

_LOGGER = logging.getLogger("multikari")


class _CountingSemaphore:
    __slots__ = ("_counter", "_limit", "_waiters")

    def __init__(self, limit: int = -1, /) -> None:
        self._counter = 0
        self._limit = limit
        self._waiters: list[asyncio.Future[None]] = []

    @property
    def is_acquired(self) -> bool:
        return bool(self._waiters)

    def __enter__(self) -> None:
        if self._counter == self._limit:
            raise RuntimeError("Semaphore is locked")

        self._counter += 1

    def __exit__(
        self,
        _: typing.Optional[type[BaseException]],
        __: typing.Optional[BaseException],
        ___: typing.Optional[types.TracebackType],
        /,
    ) -> None:
        if self._counter == 0:
            raise RuntimeError("Semaphore is not acquired")

        self._counter -= 1
        if self._counter == 0:
            self._release_waiters()

    def _release_waiters(self) -> None:
        for waiter in self._waiters.copy():
            if not waiter.done():
                waiter.set_result(None)

    async def wait_for_full_release(self) -> None:
        future = asyncio.get_running_loop().create_future()
        self._waiters.append(future)
        try:
            return await future
        finally:
            self._waiters.remove(future)


def _process_pipeline_message(message: tuple[zmq.Frame, ...], /) -> tuple[int, str, bytes]:
    # [b"{shard_id}", b"{event_name}", b"{payload}"]
    assert len(message) == 3
    shard_id = message[0].bytes
    event_name = message[1].bytes
    payload = message[2].bytes
    assert isinstance(shard_id, bytes)
    assert isinstance(event_name, bytes)
    assert isinstance(payload, bytes)
    return int(shard_id), event_name.decode(), payload


def _process_publish_message(message: tuple[zmq.Frame, ...], /) -> tuple[int, str, bytes]:
    # [b"{event_name}:{shard_id}", b"{payload}"]
    assert len(message) == 2
    topic = message[0].bytes
    payload = message[1].bytes
    assert isinstance(topic, bytes)
    assert isinstance(payload, bytes)
    event_name, shard_id = topic.split(b":", 1)
    return int(shard_id), event_name.decode(), payload


class ZmqReceiver(abc.AbstractReceiver):
    __slots__ = (
        "_ctx",
        "_is_closing",
        "_join_semaphore",
        "_pipeline_url",
        "_publish_url",
        "_pull_socket",
        "_pull_task",
        "_sub_socket",
        "_sub_task",
        "_subscriptions",
        "_zmq",
    )

    def __init__(self, pipeline_url: str, publish_url: str, /) -> None:
        import zmq
        import zmq.asyncio

        self._ctx = zmq.asyncio.Context()
        self._is_closing = False
        self._join_semaphore = _CountingSemaphore()
        self._pipeline_url = pipeline_url
        self._publish_url = publish_url
        self._pull_socket: typing.Optional[zmq.asyncio.Socket] = None
        self._pull_task: typing.Optional[asyncio.Task[None]] = None
        self._sub_socket: typing.Optional[zmq.asyncio.Socket] = None
        self._sub_task: typing.Optional[asyncio.Task[None]] = None
        self._subscriptions: dict[str, int] = {}
        self._zmq = zmq

    @property
    def is_alive(self) -> bool:
        return self._pull_task is not None

    async def connect(self, dispatch_callback: abc.DispatchSignature, sub_callback: abc.DispatchSignature, /) -> None:
        if self._pull_socket:
            raise RuntimeError("Already connected")

        loop = asyncio.get_running_loop()
        self._pull_socket = self._ctx.socket(self._zmq.PULL)
        self._pull_socket.set_hwm(1)
        self._pull_socket.connect(self._pipeline_url)
        self._pull_task = loop.create_task(
            self._dispatch_loop(self._pull_socket, dispatch_callback, _process_pipeline_message, self._rm_sub_task)
        )

        self._sub_socket = self._ctx.socket(self._zmq.SUB)
        # self._sub_socket.set_hwm(1)
        self._sub_socket.connect(self._publish_url)

        for event_name in self._subscriptions:
            self._sub_socket.setsockopt_string(self._zmq.SUBSCRIBE, event_name)

        self._sub_task = loop.create_task(
            self._dispatch_loop(self._sub_socket, sub_callback, _process_publish_message, self._rm_pull_task)
        )

    def _rm_pull_task(self) -> None:
        self._pull_task = None

    def _rm_sub_task(self) -> None:
        self._sub_task = None

    async def disconnect(self) -> None:
        if not self._pull_socket or not self._sub_socket:
            raise RuntimeError("Not connected")

        self._pull_socket.close()
        self._pull_socket = None
        self._sub_socket.close()
        self._sub_socket = None
        await self._join()

    def subscribe(self, event_name: str, /) -> None:
        try:
            self._subscriptions[event_name] += 1
        except KeyError:
            self._subscriptions[event_name] = 1

            if self._sub_socket:
                self._sub_socket.setsockopt_string(self._zmq.SUBSCRIBE, event_name)

    def unsubscribe(self, event_name: str, /) -> None:
        self._subscriptions[event_name] -= 1
        if self._subscriptions[event_name] == 0:
            del self._subscriptions[event_name]

            if self._sub_socket:
                self._sub_socket.setsockopt_string(self._zmq.UNSUBSCRIBE, event_name)

    async def _dispatch_loop(
        self,
        socket: zmq.asyncio.Socket,
        callback: abc.DispatchSignature,
        process_message: collections.Callable[[tuple[zmq.Frame, ...]], tuple[int, str, bytes]],
        on_close: collections.Callable[[], None],
    ) -> None:
        with self._join_semaphore:
            while True:
                try:
                    message: tuple[zmq.Frame, ...] = await socket.recv_multipart(copy=False)

                except self._zmq.ZMQError as exc:
                    # Indicates the socket or its context was terminated.
                    if exc.errno in (self._zmq.ETERM, self._zmq.ENOTSOCK):
                        _LOGGER.error("Socket closed with {}: {}", exc.errno, exc.strerror)
                        break

                    raise

                # This indicates that the socket was closed while we were waiting for it.
                except asyncio.CancelledError:
                    break

                try:
                    callback(*process_message(message))

                except Exception as exc:
                    _LOGGER.error("Failed to deserialize received event", exc_info=exc)

            on_close()

    async def _join(self) -> None:
        if not self._pull_task and not self._sub_task:
            raise RuntimeError("Not connected")

        if self._join_semaphore.is_acquired:
            await self._join_semaphore.wait_for_full_release()


def _load_auth(socket: zmq.Socket[bytes]) -> None:
    import zmq
    import zmq.auth

    socket.curve_publickey, socket.curve_secretkey = zmq.curve_keypair()
    socket.curve_serverkey, _ = zmq.auth.load_certificate(".curve/server.key")
