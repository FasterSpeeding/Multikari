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
import io
import itertools
import pickle
import threading
import typing
import weakref
from concurrent import futures
from multiprocessing import connection

from . import models

_ValueT = typing.TypeVar("_ValueT")
RECV_TIMEOUT: typing.Final[float] = 0.5


class Event:
    __slots__: typing.Sequence[str] = ("_flag", "_futures", "_lock")

    def __init__(self) -> None:
        self._flag = False
        self._futures: weakref.WeakSet[futures.Future[None]] = weakref.WeakSet()
        self._lock = threading.Lock()

    def is_set(self) -> bool:
        return self._flag

    def set(self) -> None:
        with self._lock:
            future: futures.Future[None]
            for future in self._futures:
                try:
                    future.set_result(None)

                except futures.InvalidStateError:
                    pass

            self._futures.clear()
            self._flag = True

    def clear(self) -> None:
        with self._lock:
            for future in self._futures:
                future.cancel()

            self._futures.clear()
            self._flag = False

    def future(self) -> futures.Future[None]:
        with self._lock:
            future: futures.Future[None] = futures.Future()

            if self._flag:
                future.set_result(None)

            else:
                self._futures.add(future)

            return future


def chunk_values(iterable: typing.Iterable[_ValueT], size: int) -> typing.Iterator[typing.Sequence[_ValueT]]:
    iterator = iter(iterable)
    while chunk := tuple(itertools.islice(iterator, size)):
        yield chunk


def poll_recv(conn: connection.Connection, event: Event) -> typing.Optional[typing.Any]:
    event_future = event.future()
    try:
        while True:
            if conn.poll(timeout=RECV_TIMEOUT):
                return conn.recv()

            if event_future.done():
                return None

    except EOFError:  # TODO: also OSError?
        return models.CloseMessage()


def poll_connections(
    connections: typing.Sequence[connection.Connection], event: Event
) -> typing.Sequence[connection.Connection]:
    event_future = event.future()
    try:
        while True:
            if conns := connection.wait(connections, timeout=RECV_TIMEOUT):
                return typing.cast("typing.Sequence[connection.Connection]", conns)

            if event_future.done():
                return []

    # TODO: how to handle this here?
    except EOFError:  # TODO: also OSError?
        return []


class PipeReadProtocol(asyncio.Protocol):
    __slots__: typing.Tuple[str, ...] = ("_buffer", "_bytes", "_close_event", "is_open", "_transport")

    def __init__(self) -> None:
        self._buffer: asyncio.Queue[bytes] = asyncio.Queue()
        self._bytes: typing.Optional[io.BytesIO] = None
        self._close_event = asyncio.Event()
        self.is_open = False
        self._transport: typing.Optional[asyncio.ReadTransport] = None

    def close(self) -> None:
        self.is_open = False
        self._close_event.set()

        if self._transport is not None:
            self._transport.close()
            self._transport = None

    def connection_lost(self, _: typing.Optional[Exception], /) -> None:
        self.is_open = False
        self._close_event.set()

    def connection_made(self, transport: asyncio.BaseTransport, /) -> None:
        if not isinstance(transport, asyncio.ReadTransport):
            raise ValueError("PipeReadProtocol can only be used with a readable connection")

        self.is_open = True
        self._transport = transport

    def data_received(self, data: bytes, /) -> None:
        self._buffer.put_nowait(data)

    def _try_get_next_entry(self) -> typing.Any:
        if self._bytes:
            # position = self._bytes.tell()
            try:
                return pickle.load(self._bytes)

            except EOFError:
                self._bytes.close()
                self._bytes = None

            # This behaviour appears to only happen on windows when data is lost and is irrecoverable
            # except pickle.UnpicklingError:
            #     self._bytes.seek(position)

        if not self._buffer.empty():
            # if self._bytes:
            #     self._bytes.write(self._buffer.pop(0))
            # else:
            self._bytes = io.BytesIO(self._buffer.get_nowait())
            return pickle.load(self._bytes)

        raise EOFError

    async def iter(self) -> typing.AsyncIterator[typing.Any]:
        close_task = asyncio.create_task(self._close_event.wait())
        while True:
            try:
                yield self._try_get_next_entry()

            except EOFError:
                if not self.is_open:
                    return

                get_task = asyncio.create_task(self._buffer.get())
                done, _ = await asyncio.wait((close_task, get_task), return_when=asyncio.FIRST_COMPLETED)

                if get_task not in done:
                    return

                self._bytes = io.BytesIO(await get_task)
                yield pickle.load(self._bytes)

    async def read(self) -> typing.Any:
        try:
            return self._try_get_next_entry()

        except EOFError:
            if self.is_open:
                close_task = asyncio.create_task(self._close_event.wait())
                get_task = asyncio.create_task(self._buffer.get())
                done, _ = await asyncio.wait((close_task, get_task), return_when=asyncio.FIRST_COMPLETED)

                if get_task in done:
                    if not self._bytes:
                        self._bytes = io.BytesIO(await get_task)

                    return pickle.load(self._bytes)

            raise EOFError() from None


class PipeWriteProtocol(asyncio.Protocol):
    __slots__: typing.Tuple[str, ...] = ("_transport",)

    def __init__(self) -> None:
        self._transport: typing.Optional[asyncio.WriteTransport] = None

    def close(self) -> None:
        if self._transport:
            self._transport.close()
            self._transport = None

    def connection_lost(self, _: typing.Optional[Exception], /) -> None:
        self._transport = None

    def connection_made(self, transport: asyncio.BaseTransport, /) -> None:
        if not isinstance(transport, asyncio.WriteTransport):
            raise ValueError("PipeWriteProtocol can only be used with a writable connection")

        self._transport = transport

    def write(self, data: typing.Any, /) -> None:
        if not self._transport:
            raise EOFError()

        self._transport.write(pickle.dumps(data))


async def wrap_read_pipe(conn: connection.Connection, /) -> PipeReadProtocol:
    _, protocol = await asyncio.get_running_loop().connect_read_pipe(PipeReadProtocol, conn)
    assert isinstance(protocol, PipeReadProtocol)
    return protocol


async def wrap_write_pipe(conn: connection.Connection, /) -> PipeWriteProtocol:
    _, protocol = await asyncio.get_running_loop().connect_write_pipe(PipeWriteProtocol, conn)
    assert isinstance(protocol, PipeWriteProtocol)
    return protocol
