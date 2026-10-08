import json

import pytest
from conftest import edge, manifest
from pydantic import ValidationError

from flamoris_update_core.errors import UpdateError
from flamoris_update_core.graph import route
from flamoris_update_core.models import Manifest
from flamoris_update_core.wire import decode, dumps, loads


@pytest.mark.parametrize(
    "raw",
    [
        b'{"a":1,"a":2}',
        b'{"a":NaN}',
        b'{"a":1.0}',
        b"[]",
        b'{"a":"\\ud800"}',
        b'{"a":' + b"[" * 20 + b"0" + b"]" * 20 + b"}",
        b'{"a":9223372036854775808}',
    ],
)
def test_wire_rejects_ambiguous_and_unbounded_json(raw):
    with pytest.raises(UpdateError):
        loads(raw)


@pytest.mark.parametrize(
    "field,value",
    [
        ("unknown", True),
        ("manifest_version", 2),
        ("release", "v1.0.0"),
        ("release", "1.0"),
        ("release", "01.0.0"),
        ("release", "1.0.0-alpha"),
    ],
)
def test_strict_manifest(field, value):
    _, raw, _, _ = manifest()
    obj = json.loads(raw)
    obj[field] = value
    with pytest.raises((UpdateError, ValidationError)):
        decode(Manifest, dumps(obj))


def test_direct_target_bundled_route_without_intermediate_release():
    m, _, _, _ = manifest("1.2.0", "db-3", [edge()])
    assert route(m, {"database": "db-1"}) == ["one-three"]
    assert route(m, {"database": "db-3"}) == []


def test_ambiguous_paths_require_signed_preference():
    m, _, _, _ = manifest("1.2.0", "db-3", [edge("a"), edge("b")])
    with pytest.raises(UpdateError, match="Operation rejected") as e:
        route(m, {"database": "db-1"})
    assert e.value.code == "ambiguous_migration_path"
    from flamoris_update_core.models import PreferredRoute

    preferred = m.model_copy(
        update={"preferred_routes": [PreferredRoute(source={"database": "db-1"}, edges=["b"])]}
    )
    assert route(preferred, {"database": "db-1"}) == ["b"]


def test_cyclic_route_and_missing_schema_rejected():
    m, _, _, _ = manifest("1.2.0", "db-3", [edge(), edge("reverse", "db-3", "db-1")])
    with pytest.raises(UpdateError):
        route(m, {"database": "db-1"})
    with pytest.raises(UpdateError):
        route(m, {})
