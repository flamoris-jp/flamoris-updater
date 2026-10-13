"""Catalog discovery reads verified origins without changing immutable recipes or Jobs."""

import copy
import os

import httpx
import pytest
from test_managed import recipe

from flamoris_update_core.wire import digest, dumps
from flamoris_updater_adapters.catalog_ui import OFFICIAL, installed_sources
from flamoris_updater_adapters.managed import Manager

pytestmark = pytest.mark.skipif(os.geteuid() != 0, reason="Protected Manager state runs in root CI")

APP = "flamoris-generation-mcp"
LATEST = "https://github.com/example/owned-generation/releases/latest/download/catalog.json"
OLD = "https://github.com/example/owned-generation/releases/download/v1.0.0/catalog.json"


@pytest.fixture
def environment(tmp_path, monkeypatch):
    monkeypatch.setattr("platform.machine", lambda: "x86_64")
    item = recipe()
    item["downloads"]["image.tar"]["url"] = OLD.rsplit("/", 1)[0] + "/image.tar"
    newer = copy.deepcopy(item)
    newer["release"] = newer["application"]["release"] = "1.1.0"
    catalogs = {
        OLD: {"catalog_version": 1, "recipes": [item]},
        LATEST: {"catalog_version": 1, "recipes": [item, newer]},
        OFFICIAL: {"catalog_version": 1, "recipes": []},
    }
    requested, offline = [], set()

    def respond(request):
        url = str(request.url)
        requested.append(url)
        if url in offline:
            raise httpx.ConnectError("test", request=request)
        return httpx.Response(200, content=dumps(catalogs[url]))

    manager = Manager(
        tmp_path / "manager",
        tmp_path / "apps",
        client=httpx.Client(transport=httpx.MockTransport(respond)),
    )
    manager.configure(OLD)
    with manager.journal.transaction() as db:
        manager.journal.put("managed_recipe", "installed-job", item, db)
        manager.journal.put(
            "managed_app",
            APP,
            {
                "application_id": APP,
                "release": "1.0.0",
                "phase": "succeeded",
                "job_id": "installed-job",
                "previous": {"release": "0.9.0"},
            },
            db,
        )
    requested.clear()
    yield manager, catalogs, requested, offline
    manager.client.close()


def test_auto_discovery_initial_manual_refresh_and_poll_only_once_per_source(environment):
    manager, catalogs, requested, offline = environment
    result = manager.invoke("updater_apps_list", {"refresh": True, "discover": True})
    assert sorted(requested) == sorted([OLD, LATEST, OFFICIAL])
    assert manager.sources() == [OLD, OFFICIAL, LATEST]
    assert not result["catalog_errors"]
    assert [r["release"] for r in result["items"][0]["releases"]] == ["1.0.0", "1.1.0"]
    requested.clear()
    manager.invoke("updater_apps_list", {})
    manager.invoke("updater_self_status", {})
    manager.invoke("updater_catalogs_list", {})
    assert requested == []
    manager.invoke("updater_apps_list", {"refresh": True, "discover": True})
    assert sorted(requested) == sorted([OLD, LATEST, OFFICIAL])
    assert manager.journal.list("managed_job") == []
    assert manager.journal.get("managed_app", APP)["previous"] == {"release": "0.9.0"}


def test_removed_auto_source_stays_removed_after_restart_and_manual_add_restores(environment):
    manager, catalogs, requested, offline = environment
    manager.invoke("updater_apps_list", {"refresh": True, "discover": True})
    manager.remove_source(LATEST)
    requested.clear()
    restarted = Manager(manager.state, manager.root, client=manager.client)
    restarted.invoke("updater_apps_list", {"refresh": True, "discover": True})
    assert LATEST not in requested and LATEST not in restarted.sources()
    assert restarted.journal.get("managed_app", APP)["release"] == "1.0.0"
    restarted.configure(LATEST)
    assert LATEST in restarted.sources()
    assert restarted.journal.get("manager_config", "removed_sources")["urls"] == []


def test_failure_keeps_snapshot_and_other_sources_continue(environment):
    manager, catalogs, requested, offline = environment
    manager.invoke("updater_apps_list", {"refresh": True, "discover": True})
    before = manager._source_catalog(LATEST)
    offline.add(LATEST)
    requested.clear()
    result = manager.invoke("updater_apps_list", {"refresh": True, "discover": True})
    assert result["catalog_errors"] == [{"url": LATEST, "error": "catalog_refresh_failed"}]
    assert manager._source_catalog(LATEST) == before
    assert OFFICIAL in requested and OLD in requested
    source = next(
        i for i in manager.invoke("updater_catalogs_list", {})["items"] if i["url"] == LATEST
    )
    assert source["checked_at"] and source["error"]
    offline.clear()
    manager.invoke("updater_apps_list", {"refresh": True, "discover": True})
    source = next(
        i for i in manager.invoke("updater_catalogs_list", {})["items"] if i["url"] == LATEST
    )
    assert source["error"] is None


def test_legacy_matching_snapshot_and_unknown_origin_are_not_guessed(environment):
    manager, catalogs, requested, offline = environment
    with manager.journal.transaction() as db:
        db.execute("DELETE FROM records WHERE kind='managed_recipe'")
    assert installed_sources(manager)[APP] == LATEST
    manager.remove_source(OLD)
    assert APP not in installed_sources(manager)
    assert installed_sources(manager) == {"flamoris-updater": OFFICIAL}
    # The removed snapshot and immutable binding remain retained.
    assert manager.journal.get("manager_source_catalog", digest(OLD.encode()))


def test_immutable_conflict_isolated_from_other_sources(environment):
    manager, catalogs, requested, offline = environment
    manager.invoke("updater_apps_list", {"refresh": True, "discover": True})
    catalogs[LATEST]["recipes"][0]["generated"]["runtime.env"] += "BAD=yes\n"
    result = manager.invoke("updater_apps_list", {"refresh": True, "discover": True})
    assert result["catalog_errors"]
    assert "BAD=yes" not in dumps(manager.catalog()).decode()
    assert manager.journal.list("managed_job") == []


def test_private_access_failure_is_visible_and_does_not_make_jobs(environment, monkeypatch):
    from flamoris_update_core.errors import UpdateError

    manager, catalogs, requested, offline = environment
    download = manager._download

    def unavailable(url, *args, **kwargs):
        if url == LATEST:
            raise UpdateError("github_access_required")
        return download(url, *args, **kwargs)

    monkeypatch.setattr(manager, "_download", unavailable)
    result = manager.invoke("updater_apps_list", {"refresh": True, "discover": True})
    assert {"url": LATEST, "error": "github_access_required"} in result["catalog_errors"]
    assert result["items"][0]["catalog_check"]["error"] == "github_access_required"
    assert OFFICIAL in manager.sources()
    assert LATEST not in manager.sources()
    assert manager.journal.list("managed_job") == []
