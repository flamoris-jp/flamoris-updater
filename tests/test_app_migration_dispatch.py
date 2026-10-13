"""App-owned schema dispatch never creates roles or databases during an update."""

from types import SimpleNamespace

import pytest

from flamoris_update_core.errors import UpdateError
from flamoris_updater_adapters.install import Installer


def test_studio_migration_verifies_private_input_and_dispatches_exact_image():
    calls = []
    source = SimpleNamespace(path="/private/migration.env", verify=lambda: calls.append("verify"))
    app = SimpleNamespace(
        application_id="flamoris-studio",
        database=SimpleNamespace(studio_migration_environment=source),
        image_id="sha256:" + "a" * 64,
    )
    installer = object.__new__(Installer)
    installer.command = lambda argv, **kwargs: calls.append((argv, kwargs))
    installer._database_migrate(app)
    assert calls[0] == "verify"
    assert calls[1] == (
        [
            "/usr/bin/docker",
            "run",
            "--rm",
            "--network",
            "host",
            "--env-file",
            "/private/migration.env",
            app.image_id,
            "alembic",
            "upgrade",
            "head",
        ],
        {"timeout": 300},
    )


def test_migration_missing_or_invalid_input_has_no_container_effect():
    installer = object.__new__(Installer)
    calls = []
    installer.command = lambda *args, **kwargs: calls.append(args)
    app = SimpleNamespace(
        application_id="flamoris-studio",
        database=SimpleNamespace(studio_migration_environment=None),
        image_id="sha256:" + "a" * 64,
    )
    with pytest.raises(UpdateError):
        installer._database_migrate(app)
    assert calls == []


def test_other_application_has_no_studio_migration_dispatch():
    installer = object.__new__(Installer)
    installer.command = lambda *args, **kwargs: pytest.fail("No migration for other apps")
    installer._database_migrate(
        SimpleNamespace(application_id="flamoris-generation-mcp", database=None)
    )
