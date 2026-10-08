"""Owner-only PostgreSQL backup with an isolated, credential-free restore probe."""

import hashlib
import os
import selectors
import signal
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from uuid import uuid4

from pydantic import Field

from .errors import UpdateError
from .journal import durable_write
from .models import ID, Model
from .resources import protected_read
from .wire import digest, dumps, loads


class PostgresBinding(Model):
    id: ID
    dsn_file: str
    schemas: list[ID] = Field(min_length=1, max_length=32)
    writer_roles: list[ID] = Field(min_length=1, max_length=32)
    pg_bin: str
    sandbox: str = "/usr/bin/bwrap"
    max_bytes: int = Field(gt=0, le=2**50)
    timeout_seconds: int = Field(default=300, ge=1, le=3600)


def command(argv, *, env=None, timeout=300):
    # Private credentials never become command arguments or public errors.
    try:
        process = subprocess.Popen(
            argv,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
        output, deadline = bytearray(), time.monotonic() + timeout
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                while selector.get_map():
                    if time.monotonic() >= deadline:
                        raise UpdateError("backup_unverified")
                    for key, _ in selector.select(min(0.1, max(0, deadline - time.monotonic()))):
                        chunk = os.read(key.fd, 64 * 1024)
                        if not chunk:
                            selector.unregister(key.fd)
                        else:
                            output.extend(chunk)
                            if len(output) > 1024 * 1024:
                                raise UpdateError("quota_exceeded")
                if process.wait(timeout=max(0.01, deadline - time.monotonic())) != 0:
                    raise UpdateError("backup_unverified")
            return bytes(output)
        finally:
            # pg_ctl's daemon is deliberately independent. Any uncompleted
            # foreground restore command and its descendants are terminated.
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            process.stdout.close()
    except (OSError, subprocess.SubprocessError):
        raise UpdateError("backup_unverified", "The fixed backup/restore program failed") from None


def file_digest(path, limit):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise UpdateError("unsafe_storage")
        if before.st_size > limit:
            raise UpdateError("quota_exceeded")
        hasher, size = hashlib.sha256(), 0
        with os.fdopen(fd, "rb", closefd=False) as stream:
            while chunk := stream.read(1024 * 1024):
                size += len(chunk)
                if size > limit:
                    raise UpdateError("quota_exceeded")
                hasher.update(chunk)
        after = os.fstat(fd)
        if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ):
            raise UpdateError("resource_changed")
        return "sha256:" + hasher.hexdigest()
    finally:
        os.close(fd)


class PostgresResource:
    def __init__(self, binding: PostgresBinding):
        self.binding = binding

    def connect(self):
        import psycopg

        raw = protected_read(Path(self.binding.dsn_file), private=True, limit=16 * 1024)
        return psycopg.connect(
            raw.decode().strip(),
            connect_timeout=5,
            autocommit=True,
            options="-c statement_timeout=30000 -c lock_timeout=3000",
        )

    def restore_preflight(self):
        if os.geteuid() == 0:
            raise UpdateError(
                "restore_unavailable", "Run the PostgreSQL Owner as its dedicated non-root account"
            )
        credential = Path(self.binding.dsn_file).resolve()
        if any(
            credential.is_relative_to(path)
            for path in [
                "/usr",
                "/bin",
                "/lib",
                "/lib64",
                Path(sys.prefix).resolve(),
                Path(sys.base_prefix).resolve(),
            ]
        ):
            raise UpdateError(
                "invalid_profile", "Production credentials must be outside isolated code mappings"
            )
        for executable in [
            Path(self.binding.sandbox),
            *(
                Path(self.binding.pg_bin) / name
                for name in ["initdb", "pg_ctl", "pg_dump", "pg_restore"]
            ),
        ]:
            if (
                not executable.is_absolute()
                or executable.is_symlink()
                or not executable.is_file()
                or executable.stat().st_uid != 0
                or executable.stat().st_mode & 0o022
            ):
                raise UpdateError("restore_unavailable")
        probe = [
            self.binding.sandbox,
            "--unshare-user",
            "--unshare-net",
            "--unshare-pid",
            "--die-with-parent",
            "--ro-bind",
            "/usr",
            "/usr",
        ]
        for directory in ["/lib", "/lib64", "/bin"]:
            if Path(directory).exists():
                probe += ["--ro-bind", directory, directory]
        probe += ["--proc", "/proc", "/usr/bin/true"]
        command(
            probe,
            env={"PATH": "/usr/bin:/bin"},
            timeout=5,
        )

    def binding_digest(self):
        with self.connect() as conn:
            identity = conn.execute(
                "SELECT system_identifier::text FROM pg_control_system()"
            ).fetchone()[0]
            database = conn.execute(
                "SELECT oid FROM pg_database WHERE datname=current_database()"
            ).fetchone()[0]
        return digest(
            dumps(
                {"cluster": identity, "database": database, "schemas": sorted(self.binding.schemas)}
            )
        )

    def fence(self):
        from psycopg import sql

        with self.connect() as conn, conn.transaction():
            for role in self.binding.writer_roles:
                conn.execute(sql.SQL("ALTER ROLE {} NOLOGIN").format(sql.Identifier(role)))
            conn.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE usename=ANY(%s) AND pid<>pg_backend_pid()",
                (self.binding.writer_roles,),
            )
        self.assert_fenced()

    def reopen(self, login_roles):
        from psycopg import sql

        if not set(login_roles) <= set(self.binding.writer_roles):
            raise UpdateError("invalid_profile")
        with self.connect() as conn, conn.transaction():
            for role in login_roles:
                conn.execute(sql.SQL("ALTER ROLE {} LOGIN").format(sql.Identifier(role)))

    def login_roles(self):
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT rolname FROM pg_roles WHERE rolname=ANY(%s) AND rolcanlogin",
                (self.binding.writer_roles,),
            ).fetchall()
        return sorted(row[0] for row in rows)

    def assert_fenced(self):
        with self.connect() as conn:
            if conn.execute(
                "SELECT 1 FROM pg_stat_activity WHERE usename=ANY(%s) LIMIT 1",
                (self.binding.writer_roles,),
            ).fetchone():
                raise UpdateError("busy")
            # Include inherited privileges; undeclared external writers fail closed.
            if conn.execute(
                "SELECT 1 FROM pg_roles r WHERE r.rolcanlogin "
                "AND r.rolname<>current_user AND EXISTS (SELECT 1 FROM pg_class c "
                "JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=ANY(%s) "
                "AND c.relkind IN ('r','p') AND has_table_privilege(r.oid,c.oid,'INSERT,UPDATE,DELETE,TRUNCATE')) LIMIT 1",
                (self.binding.schemas,),
            ).fetchone():
                raise UpdateError("writers_unfenced")

    def fingerprint(self, conn=None, role_names=None, *, include_data=True):
        from psycopg import sql

        if conn is None:
            with self.connect() as connected:
                return self.fingerprint(connected, role_names, include_data=include_data)
        with conn.transaction():
            conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            conn.execute("SET LOCAL search_path=pg_catalog")
            rows = conn.execute(
                "SELECT n.nspname,c.relname,c.relkind,pg_get_userbyid(c.relowner) "
                "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname=ANY(%s) AND c.relkind IN ('r','p','v','m','S') ORDER BY 1,2",
                (self.binding.schemas,),
            ).fetchall()
            if len(rows) > 2048:
                raise UpdateError("quota_exceeded")
            hasher, total = hashlib.sha256(), 0
            roles = conn.execute(
                "SELECT rolname,rolsuper,rolinherit,rolbypassrls FROM pg_roles "
                "WHERE rolname NOT LIKE 'pg\\_%' ESCAPE '\\' "
                "AND (%s::text[] IS NULL OR rolname=ANY(%s)) ORDER BY 1 LIMIT 2049",
                (role_names, role_names),
            ).fetchall()
            if len(roles) > 2048:
                raise UpdateError("quota_exceeded")
            hasher.update(dumps([list(row) for row in roles]))
            memberships = conn.execute(
                "SELECT pg_get_userbyid(roleid),pg_get_userbyid(member),admin_option, "
                "COALESCE(to_jsonb(m)->>'inherit_option','true'), COALESCE(to_jsonb(m)->>'set_option','true') "
                "FROM pg_auth_members m WHERE (%s::text[] IS NULL OR pg_get_userbyid(member)=ANY(%s)) ORDER BY 1,2 LIMIT 4097",
                (role_names, role_names),
            ).fetchall()
            if len(memberships) > 4096:
                raise UpdateError("quota_exceeded")
            hasher.update(dumps([list(row) for row in memberships]))
            for schema, table, kind, owner in rows:
                hasher.update(dumps([schema, table, kind, owner]))
                privileges = conn.execute(
                    "SELECT CASE WHEN a.grantee=0 THEN 'PUBLIC' ELSE pg_get_userbyid(a.grantee) END, "
                    "pg_get_userbyid(a.grantor),a.privilege_type,a.is_grantable "
                    "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace, "
                    "LATERAL aclexplode(COALESCE(c.relacl,acldefault(CASE WHEN c.relkind='S' THEN 's'::\"char\" ELSE 'r'::\"char\" END,c.relowner))) a "
                    "WHERE n.nspname=%s AND c.relname=%s ORDER BY 1,2,3,4",
                    (schema, table),
                ).fetchall()
                hasher.update(dumps(privileges))
                if include_data and kind in {"r", "m"}:
                    query = sql.SQL(
                        'SELECT to_jsonb(t)::text FROM {} t ORDER BY to_jsonb(t)::text COLLATE "C"'
                    ).format(sql.Identifier(schema, table))
                    with conn.cursor(name="probe_" + uuid4().hex) as cursor:
                        cursor.execute(query)
                        for row in cursor:
                            raw = row[0].encode()
                            total += len(raw)
                            if total > self.binding.max_bytes:
                                raise UpdateError("quota_exceeded")
                            hasher.update(len(raw).to_bytes(8, "big") + raw)
                elif include_data and kind == "S":
                    values = conn.execute(
                        sql.SQL("SELECT last_value,is_called FROM {}").format(
                            sql.Identifier(schema, table)
                        )
                    ).fetchone()
                    hasher.update(dumps(list(values)))
            constraints = conn.execute(
                "SELECT n.nspname,c.relname,k.conname,pg_get_constraintdef(k.oid),k.convalidated "
                "FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid "
                "JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=ANY(%s) ORDER BY 1,2,3",
                (self.binding.schemas,),
            ).fetchall()
            if any(not item[4] for item in constraints):
                raise UpdateError("domain_invalid")
            hasher.update(dumps(constraints))
            schema_acl = conn.execute(
                "SELECT n.nspname,pg_get_userbyid(n.nspowner), "
                "CASE WHEN a.grantee=0 THEN 'PUBLIC' ELSE pg_get_userbyid(a.grantee) END, "
                "pg_get_userbyid(a.grantor),a.privilege_type,a.is_grantable "
                "FROM pg_namespace n, LATERAL aclexplode(COALESCE(n.nspacl,acldefault('n',n.nspowner))) a "
                "WHERE n.nspname=ANY(%s) ORDER BY 1,2,3,4,5,6",
                (self.binding.schemas,),
            ).fetchall()
            hasher.update(dumps(schema_acl))
            # Data alone does not prove schema or authorization continuity.
            queries = [
                "SELECT n.nspname,c.relname,a.attname,a.attnum,format_type(a.atttypid,a.atttypmod),a.attnotnull,a.attidentity,a.attgenerated,pg_get_expr(d.adbin,d.adrelid),a.attacl::text,c.relrowsecurity,c.relforcerowsecurity FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid JOIN pg_namespace n ON n.oid=c.relnamespace LEFT JOIN pg_attrdef d ON d.adrelid=c.oid AND d.adnum=a.attnum WHERE n.nspname=ANY(%s) AND a.attnum>0 AND NOT a.attisdropped ORDER BY 1,2,4",
                "SELECT n.nspname,c.relname,pg_get_indexdef(i.indexrelid),i.indisvalid,i.indisready FROM pg_index i JOIN pg_class c ON c.oid=i.indrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=ANY(%s) ORDER BY 1,2,3",
                "SELECT n.nspname,c.relname,pg_get_viewdef(c.oid,true) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=ANY(%s) AND c.relkind IN ('v','m') ORDER BY 1,2",
                "SELECT n.nspname,p.proname,pg_get_userbyid(p.proowner),pg_get_function_identity_arguments(p.oid),pg_get_functiondef(p.oid),p.proacl::text,p.prosecdef,p.proconfig FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname=ANY(%s) AND p.prokind IN ('f','p') ORDER BY 1,2,4",
                "SELECT n.nspname,c.relname,t.tgname,pg_get_triggerdef(t.oid),t.tgenabled FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=ANY(%s) AND NOT t.tgisinternal ORDER BY 1,2,3",
                "SELECT n.nspname,c.relname,p.polname,pg_get_userbyid(c.relowner),p.polcmd,p.polpermissive,ARRAY(SELECT pg_get_userbyid(role) FROM unnest(p.polroles) role ORDER BY 1),pg_get_expr(p.polqual,p.polrelid),pg_get_expr(p.polwithcheck,p.polrelid) FROM pg_policy p JOIN pg_class c ON c.oid=p.polrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=ANY(%s) ORDER BY 1,2,3",
                "SELECT n.nspname,pg_get_userbyid(d.defaclrole),d.defaclobjtype,d.defaclacl::text FROM pg_default_acl d JOIN pg_namespace n ON n.oid=d.defaclnamespace WHERE n.nspname=ANY(%s) ORDER BY 1,2,3",
            ]
            for number, query in enumerate(queries):
                hasher.update(dumps(["catalog", number]))
                with conn.cursor(name="catalog_" + uuid4().hex) as cursor:
                    cursor.execute(query, (self.binding.schemas,))
                    for row in cursor:
                        raw = dumps(list(row))
                        total += len(raw)
                        if total > self.binding.max_bytes:
                            raise UpdateError("quota_exceeded")
                        hasher.update(len(raw).to_bytes(8, "big") + raw)
            return "sha256:" + hasher.hexdigest()

    def snapshot(self, destination: Path):
        self.assert_fenced()
        destination.mkdir(mode=0o700)
        expected = self.fingerprint()
        with self.connect() as conn:
            version = int(conn.execute("SHOW server_version_num").fetchone()[0]) // 10000
            roles = [
                list(row)
                for row in conn.execute(
                    "SELECT rolname,rolsuper,rolinherit,rolbypassrls FROM pg_roles WHERE rolname NOT LIKE 'pg\\_%' ESCAPE '\\' ORDER BY 1 LIMIT 2049"
                ).fetchall()
            ]
            if len(roles) > 2048:
                raise UpdateError("quota_exceeded")
            memberships = [
                list(row)
                for row in conn.execute(
                    "SELECT pg_get_userbyid(roleid),pg_get_userbyid(member),admin_option, COALESCE(to_jsonb(m)->>'inherit_option','true'), COALESCE(to_jsonb(m)->>'set_option','true') FROM pg_auth_members m ORDER BY 1,2 LIMIT 4097"
                ).fetchall()
            ]
            if len(memberships) > 4096:
                raise UpdateError("quota_exceeded")
            db = conn.execute(
                "SELECT datcollate,datctype,pg_encoding_to_char(encoding) FROM pg_database WHERE datname=current_database()"
            ).fetchone()
            env = {
                "PATH": "/usr/bin:/bin",
                "PGHOST": conn.info.host,
                "PGPORT": str(conn.info.port),
                "PGDATABASE": conn.info.dbname,
                "PGUSER": conn.info.user,
                "PGPASSWORD": conn.info.password or "",
            }
        argv = [
            str(Path(self.binding.pg_bin) / "pg_dump"),
            "--format=custom",
            "--no-password",
            "--file=" + str(destination / "data.dump"),
        ]
        for schema in self.binding.schemas:
            argv.append("--schema=" + schema)
        command(argv, env=env, timeout=self.binding.timeout_seconds)
        if (destination / "data.dump").stat().st_size > self.binding.max_bytes:
            raise UpdateError("quota_exceeded")
        self.assert_fenced()
        if self.fingerprint() != expected:
            raise UpdateError("resource_changed")
        index = {
            "resource": self.binding.id,
            "schemas": self.binding.schemas,
            "roles": roles,
            "memberships": memberships,
            "expected": expected,
            "version": version,
            "collate": db[0],
            "ctype": db[1],
            "encoding": db[2],
            "dump_digest": file_digest(destination / "data.dump", self.binding.max_bytes),
        }
        raw = dumps(index)
        durable_write(destination / "index.json", raw)
        return digest(raw)

    def restore_verify(self, snapshot: Path, expected_digest: str):
        self.restore_preflight()
        raw = protected_read(snapshot / "index.json", private=True)
        index = loads(raw)
        if (
            digest(raw) != expected_digest
            or index["resource"] != self.binding.id
            or file_digest(snapshot / "data.dump", self.binding.max_bytes) != index["dump_digest"]
        ):
            raise UpdateError("backup_unverified")
        sandbox, executable = Path(self.binding.sandbox), Path(sys.executable).absolute()
        if sandbox.is_symlink() or not sandbox.is_file() or sandbox.stat().st_mode & 0o022:
            raise UpdateError(
                "restore_unavailable", "A protected network-isolated restore sandbox is required"
            )
        with tempfile.TemporaryDirectory(
            prefix="pg-restore-probe-", dir=snapshot.parent
        ) as temporary:
            work = Path(temporary)
            (work / "passwd").write_text(
                f"probe:x:{os.geteuid()}:{os.getegid()}:Restore probe:/work:/bin/false\n"
            )
            (work / "group").write_text(f"probe:x:{os.getegid()}:\n")
            # Only backup bytes and a disposable directory enter this namespace.
            argv = [
                str(sandbox),
                "--unshare-user",
                "--unshare-net",
                "--unshare-pid",
                "--die-with-parent",
                "--new-session",
            ]
            for path in ("/usr", "/bin", "/lib", "/lib64"):
                if Path(path).exists():
                    argv += ["--ro-bind", path, path]
            # A dedicated SDK environment contains code, never deployment credentials.
            for prefix in dict.fromkeys(
                [Path(sys.base_prefix).resolve(), Path(sys.prefix).resolve()]
            ):
                if not prefix.is_relative_to("/usr"):
                    argv += ["--ro-bind", str(prefix), str(prefix)]
            argv += [
                "--proc",
                "/proc",
                "--dev",
                "/dev",
                "--tmpfs",
                "/tmp",
                "--ro-bind",
                str(work / "passwd"),
                "/etc/passwd",
                "--ro-bind",
                str(work / "group"),
                "/etc/group",
                "--ro-bind",
                str(snapshot),
                "/backup",
                "--bind",
                temporary,
                "/work",
                str(executable),
                "-m",
                "flamoris_update_core.postgres",
                self.binding.pg_bin,
            ]
            env = {"PATH": "/usr/bin:/bin", "HOME": "/work", "TMPDIR": "/tmp", "LANG": "C.UTF-8"}
            result = loads(command(argv, env=env, timeout=self.binding.timeout_seconds))
            if result != {"verified": True, "fingerprint": index["expected"]}:
                raise UpdateError("backup_unverified")
        return True


def isolated(pg_bin):
    """Executed inside the empty-network/file namespace; no production DSN is loaded."""
    import psycopg
    from psycopg import sql

    index = loads(Path("/backup/index.json").read_bytes())
    data, socket = Path("/work/data"), Path("/work/socket")
    socket.mkdir(mode=0o700)
    user = "probe_" + uuid4().hex
    env = {"PATH": "/usr/bin:/bin", "HOME": "/work", "LANG": "C.UTF-8"}
    command(
        [
            pg_bin + "/initdb",
            "-D",
            str(data),
            "--username=" + user,
            "--auth-local=trust",
            "--auth-host=reject",
            "--encoding=" + index["encoding"],
            "--lc-collate=" + index["collate"],
            "--lc-ctype=" + index["ctype"],
        ],
        env=env,
    )
    command(
        [
            pg_bin + "/pg_ctl",
            "-D",
            str(data),
            "-l",
            "/work/server.log",
            "-w",
            "start",
            "-o",
            "-h '' -k /work/socket -p 5432",
        ],
        env=env,
    )
    try:
        with psycopg.connect(
            host=str(socket), user=user, dbname="postgres", autocommit=True
        ) as conn:
            if (
                int(conn.execute("SHOW server_version_num").fetchone()[0]) // 10000
                != index["version"]
            ):
                raise UpdateError("backup_unverified")
            for role, superuser, inherit, bypass in index["roles"]:
                conn.execute(
                    sql.SQL("CREATE ROLE {} NOLOGIN {} {} {}").format(
                        sql.Identifier(role),
                        sql.SQL("SUPERUSER" if superuser else "NOSUPERUSER"),
                        sql.SQL("INHERIT" if inherit else "NOINHERIT"),
                        sql.SQL("BYPASSRLS" if bypass else "NOBYPASSRLS"),
                    )
                )
            for role, member, admin, inherit, set_option in index["memberships"]:
                conn.execute(
                    sql.SQL("GRANT {} TO {} {}").format(
                        sql.Identifier(role),
                        sql.Identifier(member),
                        sql.SQL("WITH ADMIN OPTION" if admin else ""),
                    )
                )
                if index["version"] >= 16:
                    conn.execute(
                        sql.SQL("GRANT {} TO {} WITH INHERIT {}, SET {}").format(
                            sql.Identifier(role),
                            sql.Identifier(member),
                            sql.SQL("TRUE" if inherit == "true" else "FALSE"),
                            sql.SQL("TRUE" if set_option == "true" else "FALSE"),
                        )
                    )
            conn.execute("CREATE DATABASE probe")
        env.update(PGHOST=str(socket), PGPORT="5432", PGUSER=user, PGDATABASE="probe")
        command(
            [pg_bin + "/pg_restore", "--exit-on-error", "--dbname=probe", "/backup/data.dump"],
            env=env,
        )
        binding = PostgresBinding(
            id=index["resource"],
            dsn_file="/unused",
            schemas=index["schemas"],
            writer_roles=["unused"],
            pg_bin=pg_bin,
            max_bytes=2**50,
        )
        with psycopg.connect(host=str(socket), user=user, dbname="probe", autocommit=True) as conn:
            actual = PostgresResource(binding).fingerprint(conn, [row[0] for row in index["roles"]])
        sys.stdout.buffer.write(
            dumps({"verified": actual == index["expected"], "fingerprint": actual})
        )
    finally:
        command([pg_bin + "/pg_ctl", "-D", str(data), "-m", "immediate", "-w", "stop"], env=env)


if __name__ == "__main__":
    isolated(sys.argv[1])
