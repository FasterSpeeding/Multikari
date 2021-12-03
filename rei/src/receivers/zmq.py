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
    import hikari

_LOGGER = logging.getLogger("multikari")


# asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


class ZmqReceiver(abc.AbstractReceiver):
    __slots__ = ("_ctx", "_is_closing", "_join_event", "_pull_socket", "_task", "_url")

    def __init__(self, url: str, /) -> None:
        self._ctx = zmq.asyncio.Context()
        self._is_closing = False
        self._join_event: typing.Optional[asyncio.Event] = None
        self._pull_socket: typing.Optional[zmq.asyncio.Socket] = None
        self._task: typing.Optional[asyncio.Task[None]] = None
        self._url = url

    @property
    def is_alive(self) -> bool:
        return self._task is not None

    async def connect(self, dispatch_callback: abc.DispatchSignature, /) -> None:
        if self._pull_socket:
            raise RuntimeError("Already connected")

        self._pull_socket = self._ctx.socket(zmq.PULL)
        self._pull_socket.set_hwm(1)
        self._pull_socket.connect(self._url)
        self._task = asyncio.get_running_loop().create_task(self._dispatch_loop(self._pull_socket, dispatch_callback))

    async def disconnect(self) -> None:
        if not self._pull_socket:
            raise RuntimeError("Not connected")

        self._pull_socket.close()
        self._pull_socket = None
        await self._join()

    def get_shard(self, _: int, /) -> typing.Optional[hikari.api.GatewayShard]:
        return None

    async def _dispatch_loop(self, socket: zmq.asyncio.Socket, callback: abc.DispatchSignature) -> None:
        try:
            while True:
                try:
                    message = await socket.recv_multipart(copy=False)
                except zmq.ZMQError as exc:
                    # Indicates the socket's context was ctemianted.
                    if exc.errno == zmq.ETERM:
                        _LOGGER.error("socket raised error, assuming it's been closed", exc_info=exc)
                        break

                    # Indicates we tried to read a socket which has been closed.
                    if exc.errno == zmq.ENOTSOCK:
                        break

                    # TODO: how to handle signal interrupts zmq.EINTR
                    raise

                # Indicates the socket was closed while we were waiting to read it.
                except asyncio.CancelledError:
                    _LOGGER.info("Socket has been closed")
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

        finally:
            if self._join_event:
                self._join_event.set()
                self._join_event = None

            self._task = None

    async def _join(self) -> None:
        if not self._task:
            raise RuntimeError("Not connected")

        if not self._join_event:
            self._join_event = asyncio.Event()

        await self._join_event.wait()


def _load_auth(socket: zmq.Socket) -> None:
    socket.curve_publickey, socket.curve_secretkey = zmq.curve_keypair()
    socket.curve_serverkey, _ = zmq.auth.load_certificate(".curve/server.key")
