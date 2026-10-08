"""Real isolated restore on Linux CI; no mocks or production connections."""

import os

import pytest

from flamoris_update_core.errors import UpdateError
from flamoris_update_core.postgres import PostgresBinding, PostgresResource, command


@pytest.fixture
def database(tmp_path):
    pg_bin = os.getenv("FLAMORIS_TEST_POSTGRES_BIN")
    if not pg_bin:
        pytest.skip("Real PostgreSQL/bubblewrap integration runs in the isolated-restore CI job")

    data, socket = tmp_path / "cluster", tmp_path / "socket"
    socket.mkdir(mode=0o700)
    command(
        [
            pg_bin + "/initdb",
            "-D",
            str(data),
            "--username=source_owner",
            "--auth-local=trust",
            "--auth-host=reject",
            "--encoding=UTF8",
            "--locale=C.UTF-8",
        ]
    )
    command(
        [
            pg_bin + "/pg_ctl",
            "-D",
            str(data),
            "-l",
            str(tmp_path / "postgres.log"),
            "-w",
            "start",
            "-o",
            f"-h '' -k {socket} -p 5432",
        ]
    )
    dsn = tmp_path / "dsn"
    dsn.write_text(f"host={socket} user=source_owner dbname=postgres")
    dsn.chmod(0o600)
    resource = PostgresResource(
        PostgresBinding(
            id="database",
            dsn_file=str(dsn),
            schemas=["domain"],
            writer_roles=["app_writer"],
            pg_bin=pg_bin,
            max_bytes=16 * 1024**2,
        )
    )
    try:
        with resource.connect() as conn:
            conn.execute("CREATE ROLE app_writer LOGIN")
            conn.execute("CREATE ROLE domain_reader NOLOGIN")
            conn.execute("GRANT domain_reader TO app_writer")
            conn.execute("ALTER ROLE source_owner SET timezone='Asia/Tokyo'")
            conn.execute("CREATE SCHEMA domain")
            conn.execute(
                "CREATE TABLE domain.history(id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, body text NOT NULL, created_at timestamptz DEFAULT '2026-10-08 01:02:03+09')"
            )
            conn.execute(
                "INSERT INTO domain.history(body) VALUES ('keep conversation'),('keep personality')"
            )
            conn.execute("GRANT USAGE ON SCHEMA domain TO domain_reader,app_writer")
            conn.execute("GRANT SELECT ON domain.history TO domain_reader")
            conn.execute("GRANT INSERT,UPDATE ON domain.history TO app_writer")
        resource.restore_preflight()
        yield resource
    finally:
        command([pg_bin + "/pg_ctl", "-D", str(data), "-m", "immediate", "-w", "stop"])


def test_real_dump_restore_validates_rows_schema_roles_and_permissions(database, tmp_path):
    database.fence()
    original = database.fingerprint()
    # Initdb's pg_monitor memberships are outside the saved application roles.
    assert (
        database.fingerprint(role_names=["source_owner", "app_writer", "domain_reader"]) == original
    )
    snapshot = tmp_path / "snapshot"
    receipt = database.snapshot(snapshot)
    assert database.restore_verify(snapshot, receipt)
    assert database.fingerprint() == original
    with database.connect() as conn:
        conn.execute("REVOKE SELECT ON domain.history FROM domain_reader")
    assert database.fingerprint() != original


def test_restore_refuses_modified_dump(database, tmp_path):
    database.fence()
    snapshot = tmp_path / "snapshot"
    receipt = database.snapshot(snapshot)
    with (snapshot / "data.dump").open("ab") as stream:
        stream.write(b"changed")
    with pytest.raises(UpdateError):
        database.restore_verify(snapshot, receipt)
