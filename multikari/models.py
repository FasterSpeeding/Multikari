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

__all__: typing.Sequence[str] = ["BotBuilderProto", "MessageType"]

import enum
import logging
import typing
import uuid

if typing.TYPE_CHECKING:
    import asyncio

    from hikari import traits


_LOGGER = logging.getLogger("hikari.multikari")
_ValueT = typing.TypeVar("_ValueT")


@enum.unique
class MessageType(int, enum.Enum):
    CLOSE = enum.auto()
    STARTED = enum.auto()


class BotBuilderProto(typing.Protocol):
    def __call__(self, client: SlaveClientProto, /) -> traits.BotAware:
        raise NotImplementedError


class SlaveClientProto(typing.Protocol):
    __slots__: typing.Sequence[str] = ()

    def send(self, message: BaseMessage, /) -> asyncio.Future[BaseMessage]:
        raise NotImplementedError

    def send_no_wait(self, message: BaseMessage, /) -> None:
        raise NotImplementedError


class BaseMessage:
    __slots__: typing.Sequence[str] = ("nonce",)

    def __init__(self, *, nonce: typing.Optional[bytes] = None) -> None:
        self.nonce = nonce or uuid.uuid4().bytes


class AckMessage(BaseMessage):
    __slots__: typing.Sequence[str] = ()


class CloseMessage(BaseMessage):
    __slots__: typing.Sequence[str] = ()


class PingMessage(BaseMessage):
    __slots__: typing.Sequence[str] = ()


class PongMessage(BaseMessage):
    __slots__: typing.Sequence[str] = ()


class StartedMessage(BaseMessage):
    __slots__: typing.Sequence[str] = ()
