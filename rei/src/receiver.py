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

import abc
import asyncio
import logging
import typing
from collections import abc as collections

import zmq
import zmq.asyncio
import zmq.auth

DispatchSignature = collections.Callable[[int, str, bytes], None]
_LOGGER = logging.getLogger("multikari")


class AbstractReceiver(abc.ABC):
    @abc.abstractmethod
    async def connect(self, dispatch_callback: DispatchSignature, sub_callback: DispatchSignature, /) -> None:
        ...

    @abc.abstractmethod
    async def disconnect(self) -> None:
        ...

    @abc.abstractmethod
    async def join(self) -> None:
        ...


class ZmqReceiver(AbstractReceiver):
    __slots__ = ("_closing_event", "_ctx", "_is_closing", "_join_event", "_socket", "_task", "_url")

    def __init__(self, url: str, /) -> None:
        self._closing_event: typing.Optional[asyncio.Event] = None
        self._ctx = zmq.asyncio.Context()
        self._is_closing = False
        self._join_event: typing.Optional[asyncio.Event] = None
        self._socket: typing.Optional[zmq.asyncio.Socket] = None
        self._task: typing.Optional[asyncio.Task[None]] = None
        self._url = url

    async def connect(self, dispatch_callback: DispatchSignature, sub_callback: DispatchSignature, /) -> None:
        if self._socket:
            raise RuntimeError("Already connected")

        self._closing_event = asyncio.Event()
        self._socket = self._ctx.socket(zmq.PULL)
        self._socket.set_hwm(1)
        self._socket.connect(self._url)
        self._task = asyncio.get_running_loop().create_task(self._dispatch_loop(dispatch_callback, self._closing_event))

    async def disconnect(self) -> None:
        if not self._socket or not self._closing_event:
            raise RuntimeError("Not connected")

        self._socket.close(linger=0)
        self._socket = None
        self._closing_event.set()
        self._closing_event = None
        await self.join()

    async def _dispatch_loop(self, callback: DispatchSignature, close_event: asyncio.Event) -> None:
        close_task = asyncio.get_running_loop().create_task(close_event.wait())
        while True:
            # recv_multipart just blocks after its finished going through the internal buffer
            # once the socket has been closed when used in blocking mode which is less than ideal.

            # Passing flags=zmq.NOBLOCK then catching the zmq.ZMQError and yielding to the event loop
            # for a bit leads to unwanted cpu usage characteristics so for now that's being avoided.

            # For some reason create_task gets deadlocked on this, so ensure_future is used.
            recv_task = asyncio.ensure_future(self._socket.recv_multipart(copy=False))
            done, _ = await asyncio.wait((recv_task, close_task), return_when=asyncio.FIRST_COMPLETED)

            if recv_task in done:
                message: list[zmq.Frame] = await recv_task

                try:
                    callback(int(message[0].bytes), message[1].bytes.decode(), message[2].bytes)
                except Exception:
                    _LOGGER.error("Failed to deserialize received event", exc_info=True)

            else:
                recv_task.cancel()
                break

        if self._join_event:
            self._join_event.set()
            self._join_event = None

        self._task = None

    async def join(self) -> None:
        if not self._task:
            raise RuntimeError("Not connected")

        if not self._join_event:
            self._join_event = asyncio.Event()

        await self._join_event.wait()


def load_auth(socket: zmq.Socket) -> None:
    socket.curve_publickey, socket.curve_secretkey = zmq.curve_keypair()
    socket.curve_serverkey, _ = zmq.auth.load_certificate(".curve/server.key")


if __name__ == "__main__":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    import json

    import hikari
    from hikari.impl import event_factory

    rest = hikari.RESTApp().acquire("gay")
    event_factory = event_factory.EventFactoryImpl(rest)
    event_manager = hikari.impl.EventManagerImpl(event_factory, hikari.Intents.ALL)

    def _handle_event(shard_id: int, event_name: str, payload: bytes, /) -> None:
        event_manager.consume_raw_event(event_name, None, json.loads(payload)["d"])
        print(shard_id, event_name)

    async def _main() -> None:
        receiver = ZmqReceiver("tcp://127.0.0.1:5555")
        await receiver.connect(_handle_event, _handle_event)
        await receiver.join()

    asyncio.run(_main())
