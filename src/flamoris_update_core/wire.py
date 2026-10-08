import hashlib
import json
import re
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from .errors import UpdateError

T = TypeVar("T", bound=BaseModel)
MAX_JSON = 1024 * 1024


def digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _pairs(items: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _no_float(_: str) -> None:
    raise ValueError("non-integer number")


def _check(value: Any, depth: int = 0) -> None:
    if depth > 16:
        raise ValueError("depth limit")
    if isinstance(value, str):
        value.encode("utf-8", errors="strict")
        if len(value) > 2 * MAX_JSON:
            raise ValueError("string limit")
    elif isinstance(value, int) and not isinstance(value, bool):
        if not -(2**63) <= value < 2**63:
            raise ValueError("integer limit")
    elif isinstance(value, dict):
        for key, item in value.items():
            _check(key, depth + 1)
            _check(item, depth + 1)
    elif isinstance(value, list):
        if len(value) > 4096:
            raise ValueError("array limit")
        for item in value:
            _check(item, depth + 1)


def loads(data: bytes, limit: int = MAX_JSON) -> dict:
    if not isinstance(data, bytes) or len(data) > limit:
        raise UpdateError("invalid_input", "JSON byte limit exceeded")
    try:
        value = json.loads(
            data.decode("utf-8", errors="strict"),
            object_pairs_hook=_pairs,
            parse_float=_no_float,
            parse_constant=_no_float,
        )
        if not isinstance(value, dict):
            raise ValueError("object required")
        _check(value)
        return value
    except (ValueError, UnicodeError, RecursionError, OverflowError):
        raise UpdateError("invalid_input", "Invalid or unsupported JSON") from None


def dumps(value: Any) -> bytes:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json", by_alias=True, exclude_none=True)
    _check(value)
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def decode(model: type[T], data: bytes, limit: int = MAX_JSON) -> T:
    try:
        return model.model_validate(loads(data, limit))
    except ValidationError:
        raise UpdateError("invalid_input", "Fields do not match the versioned contract") from None


def version(value: str) -> tuple[int, int, int]:
    if (
        not isinstance(value, str)
        or not re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", value)
        or len(value) > 64
    ):
        raise ValueError("stable SemVer required")
    return tuple(map(int, value.split(".")))
