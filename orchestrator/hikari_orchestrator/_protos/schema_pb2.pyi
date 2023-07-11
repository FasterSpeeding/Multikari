from typing import ClassVar as _ClassVar
from typing import Iterable as _Iterable
from typing import Mapping as _Mapping
from typing import Optional as _Optional
from typing import Union as _Union

from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from google.protobuf import timestamp_pb2 as _timestamp_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper

DESCRIPTOR: _descriptor.FileDescriptor

class InstructionType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = []
    DISCONNECT: _ClassVar[InstructionType]
    GATEWAY_PAYLOAD: _ClassVar[InstructionType]
    CONNECT: _ClassVar[InstructionType]

class ShardState(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = []
    STARTING: _ClassVar[ShardState]
    STARTED: _ClassVar[ShardState]
    STOPPED: _ClassVar[ShardState]

class StatusType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = []
    FAILED: _ClassVar[StatusType]
    SUCCESS: _ClassVar[StatusType]

DISCONNECT: InstructionType
GATEWAY_PAYLOAD: InstructionType
CONNECT: InstructionType
STARTING: ShardState
STARTED: ShardState
STOPPED: ShardState
FAILED: StatusType
SUCCESS: StatusType

class PresenceActivity(_message.Message):
    __slots__ = ["name", "url", "type"]
    NAME_FIELD_NUMBER: _ClassVar[int]
    URL_FIELD_NUMBER: _ClassVar[int]
    TYPE_FIELD_NUMBER: _ClassVar[int]
    name: str
    url: _Optional[str]
    type: int
    def __init__(self, name: _Optional[str] = ..., url: _Optional[str] = ..., type: _Optional[int] = ...) -> None: ...

class PresenceUpdate(_message.Message):
    __slots__ = ["idle_timestamp", "undefined_idle", "afk", "activity_payload", "undefined_activity", "status"]
    IDLE_TIMESTAMP_FIELD_NUMBER: _ClassVar[int]
    UNDEFINED_IDLE_FIELD_NUMBER: _ClassVar[int]
    AFK_FIELD_NUMBER: _ClassVar[int]
    ACTIVITY_PAYLOAD_FIELD_NUMBER: _ClassVar[int]
    UNDEFINED_ACTIVITY_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    idle_timestamp: _Optional[_timestamp_pb2.Timestamp]
    undefined_idle: _Optional[Undefined]
    afk: _Optional[bool]
    activity_payload: _Optional[PresenceActivity]
    undefined_activity: _Optional[Undefined]
    status: _Optional[str]
    def __init__(
        self,
        idle_timestamp: _Optional[_Union[_timestamp_pb2.Timestamp, _Mapping]] = ...,
        undefined_idle: _Optional[_Union[Undefined, _Mapping]] = ...,
        afk: _Optional[bool] = ...,
        activity_payload: _Optional[_Union[PresenceActivity, _Mapping]] = ...,
        undefined_activity: _Optional[_Union[Undefined, _Mapping]] = ...,
        status: _Optional[str] = ...,
    ) -> None: ...

class RequestGuildMembers(_message.Message):
    __slots__ = ["guild_id", "include_presences", "query", "limit", "users", "nonce"]
    GUILD_ID_FIELD_NUMBER: _ClassVar[int]
    INCLUDE_PRESENCES_FIELD_NUMBER: _ClassVar[int]
    QUERY_FIELD_NUMBER: _ClassVar[int]
    LIMIT_FIELD_NUMBER: _ClassVar[int]
    USERS_FIELD_NUMBER: _ClassVar[int]
    NONCE_FIELD_NUMBER: _ClassVar[int]
    guild_id: int
    include_presences: _Optional[bool]
    query: str
    limit: int
    users: _containers.RepeatedScalarFieldContainer[int]
    nonce: _Optional[str]
    def __init__(
        self,
        guild_id: _Optional[int] = ...,
        include_presences: _Optional[bool] = ...,
        query: _Optional[str] = ...,
        limit: _Optional[int] = ...,
        users: _Optional[_Iterable[int]] = ...,
        nonce: _Optional[str] = ...,
    ) -> None: ...

class VoiceState(_message.Message):
    __slots__ = ["guild_id", "channel_id", "self_mute", "self_deaf"]
    GUILD_ID_FIELD_NUMBER: _ClassVar[int]
    CHANNEL_ID_FIELD_NUMBER: _ClassVar[int]
    SELF_MUTE_FIELD_NUMBER: _ClassVar[int]
    SELF_DEAF_FIELD_NUMBER: _ClassVar[int]
    guild_id: int
    channel_id: _Optional[int]
    self_mute: _Optional[bool]
    self_deaf: _Optional[bool]
    def __init__(
        self,
        guild_id: _Optional[int] = ...,
        channel_id: _Optional[int] = ...,
        self_mute: _Optional[bool] = ...,
        self_deaf: _Optional[bool] = ...,
    ) -> None: ...

class Instruction(_message.Message):
    __slots__ = ["type", "presence_update", "voice_state", "request_guild_members", "shard_id"]
    TYPE_FIELD_NUMBER: _ClassVar[int]
    PRESENCE_UPDATE_FIELD_NUMBER: _ClassVar[int]
    VOICE_STATE_FIELD_NUMBER: _ClassVar[int]
    REQUEST_GUILD_MEMBERS_FIELD_NUMBER: _ClassVar[int]
    SHARD_ID_FIELD_NUMBER: _ClassVar[int]
    type: InstructionType
    presence_update: PresenceUpdate
    voice_state: VoiceState
    request_guild_members: RequestGuildMembers
    shard_id: _Optional[int]
    def __init__(
        self,
        type: _Optional[_Union[InstructionType, str]] = ...,
        presence_update: _Optional[_Union[PresenceUpdate, _Mapping]] = ...,
        voice_state: _Optional[_Union[VoiceState, _Mapping]] = ...,
        request_guild_members: _Optional[_Union[RequestGuildMembers, _Mapping]] = ...,
        shard_id: _Optional[int] = ...,
    ) -> None: ...

class ShardId(_message.Message):
    __slots__ = ["shard_id"]
    SHARD_ID_FIELD_NUMBER: _ClassVar[int]
    shard_id: int
    def __init__(self, shard_id: _Optional[int] = ...) -> None: ...

class Shard(_message.Message):
    __slots__ = ["state", "last_seen", "latency", "session_id", "seq", "shard_id"]
    STATE_FIELD_NUMBER: _ClassVar[int]
    LAST_SEEN_FIELD_NUMBER: _ClassVar[int]
    LATENCY_FIELD_NUMBER: _ClassVar[int]
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    SEQ_FIELD_NUMBER: _ClassVar[int]
    SHARD_ID_FIELD_NUMBER: _ClassVar[int]
    state: ShardState
    last_seen: _timestamp_pb2.Timestamp
    latency: float
    session_id: _Optional[str]
    seq: _Optional[int]
    shard_id: int
    def __init__(
        self,
        state: _Optional[_Union[ShardState, str]] = ...,
        last_seen: _Optional[_Union[_timestamp_pb2.Timestamp, _Mapping]] = ...,
        latency: _Optional[float] = ...,
        session_id: _Optional[str] = ...,
        seq: _Optional[int] = ...,
        shard_id: _Optional[int] = ...,
    ) -> None: ...

class AllShards(_message.Message):
    __slots__ = ["shards"]
    SHARDS_FIELD_NUMBER: _ClassVar[int]
    shards: _containers.RepeatedCompositeFieldContainer[Shard]
    def __init__(self, shards: _Optional[_Iterable[_Union[Shard, _Mapping]]] = ...) -> None: ...

class DisconnectResult(_message.Message):
    __slots__ = ["status", "state"]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    STATE_FIELD_NUMBER: _ClassVar[int]
    status: StatusType
    state: _Optional[Shard]
    def __init__(
        self, status: _Optional[_Union[StatusType, str]] = ..., state: _Optional[_Union[Shard, _Mapping]] = ...
    ) -> None: ...

class GatewayPayload(_message.Message):
    __slots__ = ["presence_update", "voice_state", "request_guild_members"]
    PRESENCE_UPDATE_FIELD_NUMBER: _ClassVar[int]
    VOICE_STATE_FIELD_NUMBER: _ClassVar[int]
    REQUEST_GUILD_MEMBERS_FIELD_NUMBER: _ClassVar[int]
    presence_update: PresenceUpdate
    voice_state: VoiceState
    request_guild_members: RequestGuildMembers
    def __init__(
        self,
        presence_update: _Optional[_Union[PresenceUpdate, _Mapping]] = ...,
        voice_state: _Optional[_Union[VoiceState, _Mapping]] = ...,
        request_guild_members: _Optional[_Union[RequestGuildMembers, _Mapping]] = ...,
    ) -> None: ...

class Undefined(_message.Message):
    __slots__ = []
    def __init__(self) -> None: ...
