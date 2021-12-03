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

__all__ = ["ZmqReceiver"]

import asyncio
import logging
import typing

import zmq
import zmq.asyncio
import zmq.auth

from . import abc

if typing.TYPE_CHECKING:
    import types
    from collections import abc as collections

_LOGGER = logging.getLogger("multikari")


# asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


class _CountingSeamphore:
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

    def __exit__(self, _: type[Exception], __: Exception, ___: types.TracebackType, /) -> None:
        if self._counter == 0:
            raise RuntimeError("Semaphore is not acquired")

        self._counter -= 1
        if self._counter == 0:
            self._release_waiters()

    def _release_waiters(self) -> None:
        for waiter in self._waiters:
            waiter.set_result(None)

    def wait_for_full_release(self) -> collections.Awaitable[None]:
        future = asyncio.get_running_loop().create_future()
        self._waiters.append(future)
        return future


class ZmqReceiver(abc.AbstractReceiver):
    __slots__ = (
        "_ctx",
        "_is_closing",
        "_join_semaphore",
        "_pipeline_url",
        "_pull_socket",
        "_pull_task",
        "_sub_url",
        "_sub_socket",
        "_sub_task",
        "_subscriptions",
    )

    def __init__(self, pipeline_url: str, sub_url: str, /) -> None:
        self._ctx = zmq.asyncio.Context()
        self._is_closing = False
        self._join_semaphore = _CountingSeamphore()
        self._pipeline_url = pipeline_url
        self._pull_socket: typing.Optional[zmq.asyncio.Socket] = None
        self._pull_task: typing.Optional[asyncio.Task[None]] = None
        self._sub_url = sub_url
        self._sub_socket: typing.Optional[zmq.asyncio.Socket] = None
        self._sub_task: typing.Optional[asyncio.Task[None]] = None
        self._subscriptions: dict[str, int] = {}

    @property
    def is_alive(self) -> bool:
        return self._pull_task is not None

    async def connect(self, dispatch_callback: abc.DispatchSignature, sub_callback: abc.DispatchSignature, /) -> None:
        if self._pull_socket:
            raise RuntimeError("Already connected")

        loop = asyncio.get_running_loop()
        self._pull_socket = self._ctx.socket(zmq.PULL)
        self._pull_socket.set_hwm(1)
        self._pull_socket.connect(self._pipeline_url)
        self._pull_task = loop.create_task(self._dispatch_loop(self._pull_socket, dispatch_callback))

        self._sub_socket = self._ctx.socket(zmq.SUB)
        # self._sub_socket.set_hwm(1)
        self._sub_socket.connect(self._sub_url)

        for event_name in self._subscriptions:
            self._sub_socket.setsockopt_string(zmq.SUBSCRIBE, event_name)

        self._sub_task = loop.create_task(self._dispatch_loop(self._sub_socket, sub_callback))

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
                self._sub_socket.setsockopt_string(zmq.SUBSCRIBE, event_name)

    def unsubscribe(self, event_name: str, /) -> None:
        self._subscriptions[event_name] -= 1
        if self._subscriptions[event_name] == 0:
            del self._subscriptions[event_name]

            if self._sub_socket:
                self._sub_socket.setsockopt_string(zmq.UNSUBSCRIBE, event_name)

    async def _dispatch_loop(self, socket: zmq.asyncio.Socket, callback: abc.DispatchSignature) -> None:
        with self._join_semaphore:
            while True:
                try:
                    message = await socket.recv_multipart(copy=False)

                except zmq.ZMQError as exc:
                    # Indicates the socket's context was temianted.
                    if exc.errno in (zmq.ETERM, zmq.ENOTSOCK):
                        _LOGGER.error("Socket closed with {}: {}", exc.errno, exc.strerror)
                        break

                    raise

                # This indicates that the socket was closed while we were waiting for it.
                except asyncio.CancelledError:
                    break

                try:
                    shard_id = message[0].bytes
                    event_name = message[1].bytes
                    payload = message[2].bytes
                    assert isinstance(shard_id, bytes)
                    assert isinstance(event_name, bytes)
                    assert isinstance(payload, bytes)
                    callback(int(shard_id), event_name.decode(), payload)

                except Exception as exc:
                    _LOGGER.error("Failed to deserialize received event", exc_info=exc)

            self._pull_task = None

    async def _join(self) -> None:
        if not self._pull_task:
            raise RuntimeError("Not connected")

        if self._join_semaphore.is_acquired:
            await self._join_semaphore.wait_for_full_release()


def _load_auth(socket: zmq.Socket) -> None:
    socket.curve_publickey, socket.curve_secretkey = zmq.curve_keypair()
    socket.curve_serverkey, _ = zmq.auth.load_certificate(".curve/server.key")
