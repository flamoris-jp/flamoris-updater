"""Actual SQLite view boundaries and bounded search; no installer effects."""

import re
import threading
from types import SimpleNamespace

import pytest
from starlette.testclient import TestClient

from flamoris_update_core.errors import UpdateError
from flamoris_updater_adapters.diagnostics import Log
from flamoris_updater_adapters.history import History, begin_history, search_history
from flamoris_updater_adapters.journal import Journal
from flamoris_updater_adapters.managed import Manager
from flamoris_updater_adapters.web import create_app


def put(journal, n, created=100, app="example-app", phase="succeeded", action="update"):
    identity = f"job-{n:032x}"
    value = dict(job_id=identity, created_at=created, phase=phase, action=action, release="1.0.0")
    if app is not None:
        value["application_id"] = app
    with journal.transaction() as db:
        journal.put("managed_job", identity, value, db)
    return value


def test_boundary_uses_insert_order_even_with_same_second_and_clock_skew(tmp_path):
    journal = Journal(tmp_path)
    old = put(journal, 1, 500, phase="running")
    boundary = begin_history(journal)["after_sequence"]
    fresh = put(journal, 2, 500)
    clock_back = put(journal, 3, 1)
    with journal.transaction() as db:
        journal.put("managed_job", old["job_id"], {**old, "phase": "failed_safe"}, db)
    result = search_history(journal, History(after_sequence=boundary))
    assert [j["job_id"] for j in result["items"]] == [fresh["job_id"], clock_back["job_id"]]
    # Retrying reads and restarting the adapter cannot advance a tab's boundary.
    assert search_history(Journal(tmp_path), History(after_sequence=boundary)) == result
    other_tab = begin_history(journal)["after_sequence"]
    assert search_history(journal, History(after_sequence=other_tab))["items"] == []
    assert search_history(journal, History())["items"][0]["job_id"] == fresh["job_id"]


@pytest.mark.parametrize(
    "query,expected",
    [
        ({}, [4, 3, 2, 1]),
        ({"application_id": "app-a"}, [3, 1]),
        ({"created_from": 20, "created_to": 40}, [3, 2]),
        ({"application_id": "app-a", "created_from": 20, "created_to": 40}, [3]),
        ({"application_id": "flamoris-updater"}, [4]),
        ({"application_id": "missing"}, []),
    ],
)
def test_application_and_half_open_period_filters(tmp_path, query, expected):
    journal = Journal(tmp_path)
    for n, app in [(1, "app-a"), (2, "app-b"), (3, "app-a"), (4, "flamoris-updater")]:
        put(journal, n, n * 10, app)
    assert [
        int(j["job_id"][4:], 16) for j in search_history(journal, History(**query))["items"]
    ] == expected


def test_paging_ties_and_new_insert_are_bounded_without_losing_old_records(tmp_path):
    journal = Journal(tmp_path)
    for n in range(1, 206):
        put(journal, n)
    page = search_history(journal, History(limit=20))
    assert len(page["items"]) == 20
    put(journal, 999)  # Must not move the already-open search's next pages.
    found = page["items"]
    while page["next_cursor"]:
        page = search_history(journal, History(limit=20, cursor=page["next_cursor"]))
        assert len(page["items"]) <= 20
        found += page["items"]
    assert len(found) == len({j["job_id"] for j in found}) == 205
    assert len(search_history(journal, History())["items"]) == 100


def test_unassigned_old_active_self_update_and_read_only_records(tmp_path):
    journal = Journal(tmp_path)
    put(journal, 1, app="flamoris-updater", action="self_update", phase="recovery_required")
    put(journal, 2, app=None)
    boundary = begin_history(journal)["after_sequence"]
    with journal.connection() as db:
        before = list(map(tuple, db.execute("SELECT * FROM records ORDER BY kind,id")))
    assert len(search_history(journal, History(unassigned=True))["items"]) == 1
    current = search_history(journal, History(after_sequence=boundary))
    assert current["items"] == [] and current["active_self_update"]
    with journal.connection() as db:
        assert list(map(tuple, db.execute("SELECT * FROM records ORDER BY kind,id"))) == before


@pytest.mark.parametrize(
    "data",
    [
        {"created_from": 10, "created_to": 10},
        {"created_from": 11, "created_to": 10},
        {"created_from": -1},
        {"limit": 101},
        {"limit": 0},
        {"after_sequence": -1},
        {"unassigned": True, "application_id": "app-a"},
        {"cursor": {"created_at": 0, "job_id": "' OR 1=1", "ceiling": 1}},
    ],
)
def test_invalid_query_rejected(data):
    with pytest.raises(ValueError):
        History.model_validate(data)


@pytest.mark.parametrize("prefix", ["", "/updater", "/tools/updater"])
def test_html_captures_boundary_before_js_and_details_survive_source_removal(tmp_path, prefix):
    manager = Manager(tmp_path / "manager", tmp_path / "apps")
    old = put(manager.journal, 1)
    Log(manager.journal, old["job_id"]).append("test.effect", "verified")
    coordinator = SimpleNamespace(
        journal=manager.journal,
        managed_invoke=lambda subject, name, payload: manager.invoke(name, payload),
        stopping=threading.Event(),
        wakeup=threading.Event(),
    )
    with TestClient(
        create_app(coordinator, "http://testserver", run_worker=False, base_path=prefix)
    ) as client:
        response = client.get(prefix + "/")
        boundary = int(re.search(r'name="history-boundary" content="(\d+)"', response.text)[1])
        new = put(manager.journal, 2)
        result = client.post(
            prefix + "/api/v1/tools/updater_managed_history", json={"after_sequence": boundary}
        ).json()
        assert [j["job_id"] for j in result["items"]] == [new["job_id"]]
        assert client.get(prefix + "/jobs").status_code == 200
        log = client.post(
            prefix + "/api/v1/tools/updater_managed_log_get",
            json={"application_id": "example-app", "job_id": old["job_id"]},
        )
        assert log.status_code == 200 and log.json()["items"][0]["operation"] == "test.effect"
        with pytest.raises(UpdateError):
            manager.invoke(
                "updater_managed_log_get", {"application_id": "wrong-app", "job_id": old["job_id"]}
            )
    manager.client.close()
