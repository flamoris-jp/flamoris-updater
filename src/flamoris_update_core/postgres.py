"""Application-owned PostgreSQL identity and writer fencing; no backup or restore."""

import hashlib
from pathlib import Path
from uuid import uuid4

from pydantic import Field

from .errors import UpdateError
from .models import ID, Model
from .resources import protected_read
from .wire import digest, dumps


class PostgresBinding(Model):
    id: ID
    dsn_file: str
    schemas: list[ID] = Field(min_length=1, max_length=32)
    writer_roles: list[ID] = Field(min_length=1, max_length=32)
    max_bytes: int = Field(gt=0, le=2**50)
    timeout_seconds: int = Field(default=300, ge=1, le=3600)


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
            conn.execute("SET LOCAL timezone='UTC'")
            conn.execute("SET LOCAL datestyle='ISO, YMD'")
            conn.execute("SET LOCAL intervalstyle='postgres'")
            conn.execute("SET LOCAL extra_float_digits=3")
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
                "WHERE left(rolname,3)<>'pg_' "
                "AND (%s::text[] IS NULL OR rolname=ANY(%s)) ORDER BY 1 LIMIT 2049",
                (role_names, role_names),
            ).fetchall()
            if len(roles) > 2048:
                raise UpdateError("quota_exceeded")
            hasher.update(dumps([list(row) for row in roles]))
            memberships = conn.execute(
                "SELECT pg_get_userbyid(roleid),pg_get_userbyid(member),admin_option, "
                "COALESCE(to_jsonb(m)->>'inherit_option','true'), COALESCE(to_jsonb(m)->>'set_option','true') "
                "FROM pg_auth_members m WHERE pg_get_userbyid(member)=ANY(%s) ORDER BY 1,2 LIMIT 4097",
                ([row[0] for row in roles],),
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
