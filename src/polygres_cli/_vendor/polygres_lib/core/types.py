from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass, field
from typing import Any

from pydantic_core import core_schema


class _SecretPayload:
    __slots__ = ("value",)

    def __init__(self, value: str) -> None:
        self.value = value

    def __repr__(self) -> str:
        return "<redacted>"

    def __deepcopy__(self, memo: dict[int, object]) -> _SecretPayload:
        return self


@dataclass(frozen=True, slots=True, repr=False, init=False)
class SecretValue:
    _value: _SecretPayload = field(repr=False)

    def __init__(self, value: str) -> None:
        if not isinstance(value, str):
            raise TypeError("secret value must be a string")
        size = len(value.encode("utf-8"))
        if size < 1 or size > 8192:
            raise ValueError("secret value must contain 1..8192 UTF-8 bytes")
        object.__setattr__(self, "_value", _SecretPayload(value))

    def reveal(self) -> str:
        return self._value.value

    def sha256_hex(self) -> str:
        return hashlib.sha256(self.reveal().encode("utf-8")).hexdigest()

    def constant_time_equals(self, other: SecretValue) -> bool:
        if not isinstance(other, SecretValue):
            return False
        return hmac.compare_digest(self.reveal(), other.reveal())

    def __repr__(self) -> str:
        return f"{type(self).__name__}(<redacted>)"

    def __str__(self) -> str:
        return "<redacted>"

    @classmethod
    def __get_pydantic_core_schema__(cls, source_type: Any, handler: Any) -> core_schema.CoreSchema:
        del source_type, handler

        def construct(value: str) -> SecretValue:
            return cls(value)

        def deny_serialization(value: SecretValue) -> str:
            del value
            raise TypeError("secret values require an explicit reveal adapter")

        string_schema = core_schema.str_schema(min_length=1, max_length=8192)
        return core_schema.json_or_python_schema(
            json_schema=core_schema.no_info_after_validator_function(
                construct,
                string_schema,
            ),
            python_schema=core_schema.union_schema(
                [
                    core_schema.is_instance_schema(cls),
                    core_schema.no_info_after_validator_function(construct, string_schema),
                ]
            ),
            serialization=core_schema.plain_serializer_function_ser_schema(
                deny_serialization,
                info_arg=False,
                return_schema=string_schema,
            ),
        )


@dataclass(frozen=True, slots=True, repr=False, init=False)
class SecretCredential(SecretValue):
    kind_hint: object | None = field(default=None, repr=False)

    def __init__(self, value: str, kind_hint: object | None = None) -> None:
        SecretValue.__init__(self, value)
        object.__setattr__(self, "kind_hint", kind_hint)


@dataclass(frozen=True, slots=True, repr=False, init=False)
class SecretPassword(SecretValue):
    pass
