"""The one-time catalog switch preserves 1.0.3 state and immutable bindings."""

import runpy
from pathlib import Path

import pytest

from flamoris_update_core.errors import UpdateError
from flamoris_update_core.wire import decode, digest, dumps
from flamoris_updater_adapters.managed import Catalog, Manager

SCRIPT = runpy.run_path("scripts/prepare_103_catalog.py")
bind = SCRIPT["bind"]


@pytest.fixture
def legacy(tmp_path):
    manager = Manager(tmp_path / "manager", tmp_path / "apps")
    with manager.journal.transaction() as db:
        manager.journal.put(
            "self_installation", "current", {"release": "1.0.3", "phase": "succeeded"}, db
        )
        manager.journal.put(
            "manager_config", "source", {"url": "https://old.example.invalid/catalog"}, db
        )
        manager.journal.put("managed_app", "saved", {"settings": {"PRIVATE": "preserve"}}, db)
        manager.journal.put(
            "managed_job", "history", {"phase": "succeeded", "result": "preserve"}, db
        )
    raw = Path("catalogs/flamoris-20261011.json").read_bytes()
    assert digest(raw) == SCRIPT["DIGEST"]
    yield manager, decode(Catalog, raw)
    manager.client.close()


def records(manager):
    with manager.journal.connection() as db:
        return [tuple(row) for row in db.execute("SELECT * FROM records ORDER BY kind,id")]


def test_check_and_switch_preserve_state_and_history(legacy):
    manager, catalog = legacy
    before = records(manager)
    bind(manager, catalog, check=True)
    assert records(manager) == before
    bind(manager, catalog)
    assert manager.journal.get("manager_config", "source")["url"] == SCRIPT["URL"]
    assert manager.catalog() == catalog
    assert manager.journal.get("managed_app", "saved")["settings"] == {"PRIVATE": "preserve"}
    assert manager.journal.get("managed_job", "history")["result"] == "preserve"
    assert manager.journal.get("self_installation", "current")["release"] == "1.0.3"
    bind(manager, catalog)
    assert manager.catalog() == catalog


@pytest.mark.parametrize(
    "phase", ["accepted", "running", "intent", "recovery_required", "awaiting_setup"]
)
def test_unfinished_job_stops_before_changes(legacy, phase):
    manager, catalog = legacy
    with manager.journal.transaction() as db:
        manager.journal.put("managed_job", "unfinished", {"phase": phase}, db)
    before = records(manager)
    with pytest.raises(UpdateError, match="Resolve existing Jobs"):
        bind(manager, catalog)
    assert records(manager) == before


def test_immutable_collision_is_atomic(legacy):
    manager, catalog = legacy
    recipe = catalog.recipes[-1]
    identity = digest(
        dumps(
            dict(
                application_id=recipe.application_id,
                release=recipe.release,
                platform=recipe.platform,
            )
        )
    )
    with manager.journal.transaction() as db:
        manager.journal.put("catalog_recipe", identity, {"digest": "sha256:" + "0" * 64}, db)
    before = records(manager)
    with pytest.raises(UpdateError, match="immutable"):
        bind(manager, catalog)
    assert records(manager) == before


def test_other_release_stops_before_changes(legacy):
    manager, catalog = legacy
    with manager.journal.transaction() as db:
        manager.journal.put(
            "self_installation", "current", {"release": "1.0.4", "phase": "succeeded"}, db
        )
    before = records(manager)
    with pytest.raises(UpdateError, match="idle installed 1.0.3"):
        bind(manager, catalog)
    assert records(manager) == before
