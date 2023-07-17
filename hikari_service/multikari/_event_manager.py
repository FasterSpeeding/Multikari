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

__all__ = ["EventManager"]

import asyncio
import json
import typing

import hikari
import hikari.iterators

if typing.TYPE_CHECKING:
    import types
    from collections import abc as collections

    from hikari.api import event_manager as event_manager_api
    from typing_extensions import Self

    from . import _receivers

    _ConverterSig = collections.Callable[[hikari.api.GatewayShard, dict[str, typing.Any]], hikari.Event]

_DATA_KEY = "d"
_EventT = typing.TypeVar("_EventT", bound=hikari.Event)


class EventStream(hikari.api.EventStream[_EventT]):
    __slots__ = (
        "_buffer",
        "_event_manager",
        "_event_type",
        "_filters",
        "_is_active",
        "_limit",
        "_receive_event",
        "_timeout",
    )

    def __init__(
        self,
        event_manager: EventManager,
        event_type: type[_EventT],
        *,
        timeout: typing.Union[float, int, None],
        limit: typing.Optional[int] = None,
    ) -> None:
        self._buffer: list[_EventT] = []
        self._event_manager = event_manager
        self._event_type = event_type
        self._filters: hikari.iterators.All[_EventT] = hikari.iterators.All(())
        self._is_active = False
        self._limit = limit
        self._receive_event: typing.Optional[asyncio.Event] = None
        self._timeout = timeout

    @property
    def event_type(self) -> type[_EventT]:
        return self._event_type

    def __enter__(self) -> Self:
        self.open()
        return self

    def __exit__(
        self,
        _: typing.Optional[type[BaseException]],
        __: typing.Optional[BaseException],
        ___: typing.Optional[types.TracebackType],
        /,
    ) -> None:
        self.close()

    async def __anext__(self) -> _EventT:
        if not self._is_active:
            raise RuntimeError("Stream is inactive")

        while not self._buffer:
            if not self._receive_event:
                self._receive_event = asyncio.Event()

            try:
                await asyncio.wait_for(self._receive_event.wait(), timeout=self._timeout)
            except asyncio.TimeoutError:
                raise StopAsyncIteration from None

            self._receive_event.clear()

        return self._buffer.pop(0)

    def __await__(self) -> collections.Generator[None, None, collections.Sequence[_EventT]]:
        return self._await_all().__await__()

    async def _await_all(self) -> collections.Sequence[_EventT]:
        self.open()
        result = [event async for event in self]
        self.close()
        return result

    def on_event(self, event: _EventT, /) -> None:
        if not self._filters(event) or (self._limit is not None and len(self._buffer) >= self._limit):
            return

        self._buffer.append(event)
        if self._receive_event:
            self._receive_event.set()

    def close(self) -> None:
        if self._is_active:
            self._event_manager.remove_active_stream(self)
            self._is_active = False

    def filter(
        self,
        *predicates: typing.Union[tuple[str, typing.Any], collections.Callable[[_EventT], bool]],
        **attrs: typing.Any,
    ) -> Self:
        filter_ = self._map_predicates_and_attr_getters("filter", *predicates, **attrs)
        if self._is_active:
            self._buffer = [entry for entry in self._buffer if filter_(entry)]

        self._filters |= filter_
        return self

    def open(self) -> None:
        if not self._is_active:
            self._event_manager.add_active_stream(self)
            self._is_active = True


_EVENT_TO_NAMES: dict[type[typing.Any], list[str]] = {
    hikari.GuildChannelCreateEvent: ["CHANNEL_CREATE"],
    hikari.GuildChannelUpdateEvent: ["CHANNEL_UPDATE"],
    hikari.GuildChannelDeleteEvent: ["CHANNEL_DELETE"],
    hikari.GuildPinsUpdateEvent: ["CHANNEL_PINS_UPDATE"],
    hikari.DMPinsUpdateEvent: ["CHANNEL_PINS_UPDATE"],
    hikari.InviteCreateEvent: ["INVITE_CREATE"],
    hikari.InviteDeleteEvent: ["INVITE_DELETE"],
    hikari.WebhookUpdateEvent: ["WEBHOOKS_UPDATE"],
    hikari.GuildAvailableEvent: ["GUILD_CREATE"],
    hikari.GuildJoinEvent: ["GUILD_CREATE"],
    hikari.GuildLeaveEvent: ["GUILD_DELETE"],
    hikari.GuildUnavailableEvent: ["GUILD_DELETE"],
    hikari.GuildUpdateEvent: ["GUILD_UPDATE"],
    hikari.BanCreateEvent: ["GUILD_BAN_ADD"],
    hikari.BanDeleteEvent: ["GUILD_BAN_REMOVE"],
    hikari.EmojisUpdateEvent: ["GUILD_EMOJIS_UPDATE"],
    hikari.IntegrationCreateEvent: ["INTEGRATION_CREATE"],
    hikari.IntegrationUpdateEvent: ["INTEGRATION_UPDATE"],
    hikari.IntegrationDeleteEvent: ["INTEGRATION_DELETE"],
    hikari.PresenceUpdateEvent: ["PRESENCE_UPDATE"],
    hikari.InteractionCreateEvent: ["INTERACTION_CREATE"],
    hikari.MemberCreateEvent: ["GUILD_MEMBER_ADD"],
    hikari.MemberUpdateEvent: ["GUILD_MEMBER_UPDATE"],
    hikari.MemberDeleteEvent: ["GUILD_MEMBER_REMOVE"],
    hikari.GuildMessageCreateEvent: ["MESSAGE_CREATE"],
    hikari.DMMessageCreateEvent: ["MESSAGE_CREATE"],
    hikari.GuildMessageUpdateEvent: ["MESSAGE_UPDATE"],
    hikari.DMMessageUpdateEvent: ["MESSAGE_UPDATE"],
    hikari.GuildMessageDeleteEvent: ["MESSAGE_DELETE"],
    hikari.DMMessageDeleteEvent: ["MESSAGE_DELETE"],
    hikari.GuildBulkMessageDeleteEvent: ["MESSAGE_DELETE_BULK"],
    hikari.GuildReactionAddEvent: ["MESSAGE_REACTION_ADD"],
    hikari.GuildReactionDeleteEvent: ["MESSAGE_REACTION_REMOVE"],
    hikari.GuildReactionDeleteEmojiEvent: ["MESSAGE_REACTION_REMOVE_EMOJI"],
    hikari.GuildReactionDeleteAllEvent: ["MESSAGE_REACTION_REMOVE_ALL"],
    hikari.DMReactionAddEvent: ["MESSAGE_REACTION_ADD"],
    hikari.DMReactionDeleteEvent: ["MESSAGE_REACTION_REMOVE"],
    hikari.DMReactionDeleteEmojiEvent: ["MESSAGE_REACTION_REMOVE_EMOJI"],
    hikari.DMReactionDeleteAllEvent: ["MESSAGE_REACTION_REMOVE_ALL"],
    hikari.RoleCreateEvent: ["GUILD_ROLE_CREATE"],
    hikari.RoleUpdateEvent: ["GUILD_ROLE_UPDATE"],
    hikari.RoleDeleteEvent: ["GUILD_ROLE_DELETE"],
    # TODO: this needs to be exported top-level
    hikari.events.ApplicationCommandPermissionsUpdateEvent: ["APPLICATION_COMMAND_PERMISSIONS_UPDATE"],
    hikari.ScheduledEventCreateEvent: ["GUILD_SCHEDULED_EVENT_CREATE"],
    hikari.ScheduledEventDeleteEvent: ["GUILD_SCHEDULED_EVENT_DELETE"],
    hikari.ScheduledEventUpdateEvent: ["GUILD_SCHEDULED_EVENT_UPDATE"],
    hikari.ScheduledEventUserAddEvent: ["GUILD_SCHEDULED_EVENT_USER_ADD"],
    hikari.ScheduledEventUserRemoveEvent: ["GUILD_SCHEDULED_EVENT_USER_REMOVE"],
    hikari.StickersUpdateEvent: ["GUILD_STICKERS_UPDATE"],
    hikari.GuildThreadCreateEvent: ["THREAD_CREATE"],
    hikari.GuildThreadAccessEvent: ["THREAD_CREATE"],
    hikari.GuildThreadUpdateEvent: ["THREAD_UPDATE"],
    hikari.GuildThreadDeleteEvent: ["THREAD_DELETE"],
    hikari.ThreadListSyncEvent: ["THREAD_LIST_SYNC"],
    hikari.ThreadMembersUpdateEvent: ["THREAD_MEMBERS_UPDATE"],
    # TODO: shard and lifetime events???,
    hikari.ShardReadyEvent: ["READY"],
    hikari.ShardResumedEvent: ["RESUMED"],
    hikari.MemberChunkEvent: ["GUILD_MEMBERS_CHUNK"],
    hikari.GuildTypingEvent: ["TYPING_START"],
    hikari.DMTypingEvent: ["TYPING_START"],
    hikari.OwnUserUpdateEvent: ["USER_UPDATE"],
    hikari.VoiceStateUpdateEvent: ["VOICE_STATE_UPDATE"],
    hikari.VoiceServerUpdateEvent: ["VOICE_SERVER_UPDATE"],
}


for _event_type, _names in _EVENT_TO_NAMES.copy().items():
    # mro also includes the event itself so...
    for _parent_cls in _event_type.mro():
        # issubclass(Event, Event) is True btw
        if not issubclass(_parent_cls, hikari.Event) or _parent_cls is _event_type:
            continue

        try:
            _other_names = _EVENT_TO_NAMES[_parent_cls]
        except KeyError:
            _EVENT_TO_NAMES[_parent_cls] = _names.copy()

        else:
            for _name in _names:
                if _name not in _other_names:
                    _other_names.append(_name)


class _EventConverter:
    __slots__ = ("_name_to_converter",)

    def __init__(self, event_factory: hikari.api.EventFactory) -> None:
        self._name_to_converter: dict[str, typing.Optional[_ConverterSig]] = {
            "READY": event_factory.deserialize_ready_event,
            "RESUMED": lambda s, _: event_factory.deserialize_resumed_event(s),
            "APPLICATION_COMMAND_PERMISSIONS_UPDATE": event_factory.deserialize_application_command_permission_update_event,
            "CHANNEL_CREATE": event_factory.deserialize_guild_channel_create_event,
            "CHANNEL_UPDATE": event_factory.deserialize_guild_channel_update_event,
            "CHANNEL_DELETE": event_factory.deserialize_guild_channel_delete_event,
            "CHANNEL_PINS_UPDATE": event_factory.deserialize_channel_pins_update_event,
            "GUILD_CREATE": lambda s, p: (
                event_factory.deserialize_guild_available_event(s, p)
                if "unavailable" in p
                else event_factory.deserialize_guild_join_event(s, p)
            ),
            "GUILD_UPDATE": event_factory.deserialize_guild_update_event,
            "GUILD_DELETE": lambda s, p: (
                event_factory.deserialize_guild_unavailable_event(s, p)
                if p.get("unavailable", False)
                else event_factory.deserialize_guild_leave_event(s, p)
            ),
            "GUILD_BAN_ADD": event_factory.deserialize_guild_ban_add_event,
            "GUILD_BAN_REMOVE": event_factory.deserialize_guild_ban_remove_event,
            "GUILD_EMOJIS_UPDATE": event_factory.deserialize_guild_emojis_update_event,
            "GUILD_INTEGRATIONS_UPDATE": None,
            "INTEGRATION_CREATE": event_factory.deserialize_integration_create_event,
            "INTEGRATION_DELETE": event_factory.deserialize_integration_delete_event,
            "INTEGRATION_UPDATE": event_factory.deserialize_integration_update_event,
            "GUILD_MEMBER_ADD": event_factory.deserialize_guild_member_add_event,
            "GUILD_MEMBER_REMOVE": event_factory.deserialize_guild_member_remove_event,
            "GUILD_MEMBER_UPDATE": event_factory.deserialize_guild_member_update_event,
            "GUILD_MEMBERS_CHUNK": event_factory.deserialize_guild_member_chunk_event,
            "PRESENCE_UPDATE": event_factory.deserialize_presence_update_event,
            "GUILD_ROLE_CREATE": event_factory.deserialize_guild_role_create_event,
            "GUILD_ROLE_UPDATE": event_factory.deserialize_guild_role_update_event,
            "GUILD_ROLE_DELETE": event_factory.deserialize_guild_role_delete_event,
            "GUILD_SCHEDULED_EVENT_CREATE": event_factory.deserialize_scheduled_event_create_event,
            "GUILD_SCHEDULED_EVENT_DELETE": event_factory.deserialize_scheduled_event_delete_event,
            "GUILD_SCHEDULED_EVENT_UPDATE": event_factory.deserialize_scheduled_event_update_event,
            "GUILD_SCHEDULED_EVENT_USER_ADD": event_factory.deserialize_scheduled_event_user_add_event,
            "GUILD_SCHEDULED_EVENT_USER_REMOVE": event_factory.deserialize_scheduled_event_user_remove_event,
            "GUILD_STICKERS_UPDATE": event_factory.deserialize_guild_stickers_update_event,
            "INVITE_CREATE": event_factory.deserialize_invite_create_event,
            "INVITE_DELETE": event_factory.deserialize_invite_delete_event,
            "MESSAGE_CREATE": event_factory.deserialize_message_create_event,
            "MESSAGE_UPDATE": event_factory.deserialize_message_update_event,
            "MESSAGE_DELETE": event_factory.deserialize_message_delete_event,
            "MESSAGE_DELETE_BULK": event_factory.deserialize_guild_message_delete_bulk_event,
            "MESSAGE_REACTION_ADD": event_factory.deserialize_message_reaction_add_event,
            "MESSAGE_REACTION_REMOVE": event_factory.deserialize_message_reaction_remove_event,
            "MESSAGE_REACTION_REMOVE_ALL": event_factory.deserialize_message_reaction_remove_all_event,
            # TODO: Remove dm events that'd never happen
            "MESSAGE_REACTION_REMOVE_EMOJI": event_factory.deserialize_message_reaction_remove_emoji_event,
            "THREAD_CREATE": lambda s, p: (
                event_factory.deserialize_guild_thread_create_event(s, p)
                if "newly_created" in p
                else event_factory.deserialize_guild_thread_access_event(s, p)
            ),
            "THREAD_UPDATE": event_factory.deserialize_guild_thread_update_event,
            "THREAD_DELETE": event_factory.deserialize_guild_thread_delete_event,
            "THREAD_LIST_SYNC": event_factory.deserialize_thread_list_sync_event,
            "THREAD_MEMBERS_UPDATE": event_factory.deserialize_thread_members_update_event,
            "THREAD_MEMBER_UPDATE": None,
            "TYPING_START": event_factory.deserialize_typing_start_event,
            "USER_UPDATE": event_factory.deserialize_own_user_update_event,
            "VOICE_STATE_UPDATE": event_factory.deserialize_voice_state_update_event,
            "VOICE_SERVER_UPDATE": event_factory.deserialize_voice_server_update_event,
            "WEBHOOKS_UPDATE": event_factory.deserialize_webhook_update_event,
            "INTERACTION_CREATE": event_factory.deserialize_interaction_create_event,
        }

    def get_converter(self, event_name: str) -> typing.Optional[_ConverterSig]:
        return self._name_to_converter[event_name]


# TODO: catch errors
class EventManager(hikari.impl.EventManagerBase):  # TODO: maybe remove EventManagerBase all together.
    __slots__ = ("__converter", "__listeners", "__load", "__receiver", "__streams", "__waiters")

    def __init__(
        self,
        receiver: _receivers.abc.AbstractReceiver,
        event_factory: hikari.api.EventFactory,
        intents: hikari.Intents,
        /,
        load: collections.Callable[[bytes], dict[str, typing.Any]] = json.loads,
    ) -> None:
        super().__init__(event_factory, intents)
        self.__converter = _EventConverter(event_factory)
        self.__listeners: dict[str, list[event_manager_api.CallbackT[typing.Any]]] = {}
        self.__load = load
        self.__receiver = receiver
        self.__streams: dict[str, list[EventStream[typing.Any]]] = {}
        self.__waiters: dict[
            str, list[tuple[asyncio.Future[hikari.Event], typing.Optional[event_manager_api.PredicateT[typing.Any]]]]
        ] = {}

    def _load(self, data: bytes) -> dict[str, typing.Any]:
        return self.__load(data)[_DATA_KEY]

    def consume_pipeline_event(self, event_name: str, shard: hikari.api.GatewayShard, data: bytes, /) -> None:
        if listeners := self.__listeners.get(event_name):
            if converter := self.__converter.get_converter(event_name):
                event = converter(shard, self._load(data))
                asyncio.gather(*(self._invoke_callback(callback, event) for callback in listeners))

    def consume_subbed_event(self, event_name: str, shard: hikari.api.GatewayShard, data: bytes, /) -> None:
        converter = self.__converter.get_converter(event_name)
        if converter is None:
            return

        event: typing.Optional[hikari.Event] = None
        if streams := self.__streams.get(event_name):
            event = converter(shard, self._load(data))

            for stream in streams:
                stream.on_event(event)

        waiters = self.__waiters.get(event_name)
        if not waiters:
            return

        if not event:
            event = converter(shard, self._load(data))

        for waiter in waiters:
            future, predicate = waiter
            # TODO: do we need to check future.done here?
            # if not future.done():
            try:
                if predicate and not predicate(event):
                    continue
            except Exception:
                future.set_exception(Exception)
            else:
                future.set_result(event)

    def add_active_stream(self, stream: EventStream[_EventT], /) -> None:
        for name in _EVENT_TO_NAMES[stream.event_type]:
            self.__receiver.subscribe(name)
            try:
                self.__streams[name].append(stream)
            except KeyError:
                self.__streams[name] = [stream]

    def remove_active_stream(self, stream: EventStream[_EventT], /) -> None:
        for name in _EVENT_TO_NAMES[stream.event_type]:
            self.__streams[name].remove(stream)
            try:
                self.__receiver.unsubscribe(name)
            except KeyError:
                pass

    def subscribe(
        self,
        event_type: type[typing.Any],
        callback: event_manager_api.CallbackT[typing.Any],
        *,
        _nested: int = 0,
    ) -> None:
        super().subscribe(event_type, callback, _nested=_nested + 1)
        for name in _EVENT_TO_NAMES[event_type]:
            try:
                self.__listeners[name].append(callback)
            except KeyError:
                self.__listeners[name] = [callback]

    def unsubscribe(
        self,
        event_type: type[typing.Any],
        callback: event_manager_api.CallbackT[typing.Any],
    ) -> None:
        super().unsubscribe(event_type, callback)
        for name in _EVENT_TO_NAMES[event_type]:
            self.__listeners[name].remove(callback)

    def stream(
        self,
        event_type: type[_EventT],
        /,
        timeout: typing.Union[float, int, None],
        limit: typing.Optional[int] = None,
    ) -> event_manager_api.EventStream[_EventT]:
        return EventStream(self, event_type, timeout=timeout, limit=limit)

    async def wait_for(
        self,
        event_type: type[_EventT],
        /,
        timeout: typing.Union[float, int, None],
        predicate: typing.Optional[event_manager_api.PredicateT[_EventT]] = None,
    ) -> _EventT:
        future = asyncio.get_running_loop().create_future()
        names = _EVENT_TO_NAMES[event_type]
        waiter = (future, predicate)

        for name in names:
            self.__receiver.subscribe(name)
            try:
                self.__waiters[name].append(waiter)
            except KeyError:
                self.__waiters[name] = [waiter]

        try:
            return await asyncio.wait_for(future, timeout)

        finally:
            for name in names:
                self.__waiters[name].remove(waiter)
                try:
                    self.__receiver.unsubscribe(name)
                except KeyError:
                    pass
