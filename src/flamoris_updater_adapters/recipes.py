"""Portable first-install recipes for prebuilt FLAMORIS release candidates.

The application source/image owns SQL and initialization. There are no deployed
host identities, models, runtime units or existing application credentials here.
"""

from .managed import Catalog, Recipe, https


def setting(key, label, default="", *, secret=False, required=False, generate=False, kind="text"):
    return dict(
        key=key,
        label=label,
        default=default,
        secret=secret,
        required=required,
        generate=generate,
        kind=kind,
    )


def build_recipe(candidate, origin):
    https(origin)
    app, release = candidate["application_id"], candidate["release"]
    files = candidate["files"]
    downloads = {
        name: {"url": origin.rstrip("/") + "/" + name, "digest": value}
        for name, value in files.items()
    }
    generated = {}
    settings = []
    dirs = [{"path": "${root}/config"}]
    copies = []

    def file(name, *, private=False):
        return {
            "path": "${package}/" + name,
            "digest": files.get(name, "generated"),
            "private": private,
        }

    def data(name, target, *, readonly=False):
        dirs.append(
            {
                "path": "${root}/" + name,
                "uid": 10001,
                "gid": 10001,
                "mode": 0o755 if readonly else 0o750,
            }
        )
        return {"source": "${root}/" + name, "target": target, "read_only": readonly}

    ports = {
        "flamoris-generation-mcp": 8765,
        "flamoris-intelligence-mcp": 8767,
        "flamoris-ai-agent": 8768,
        "flamoris-mcp-hub": 8769,
        "flamoris-studio": 5087,
        "flamoris-gpu-node-manager": 8090,
    }
    settings.append(setting("PORT", "待受ポート", str(ports[app]), kind="port"))
    base = {
        "application_id": app,
        "release": release,
        "directories": dirs,
        "files": copies,
        "health_url": "http://127.0.0.1:${PORT}/healthz",
    }
    if app == "flamoris-gpu-node-manager":
        wheels = [file(n) for n in files if n.endswith(".whl")]
        if not wheels:
            raise ValueError("Native candidate must include a complete wheelhouse")
        dirs.append({"path": "${root}/releases/${release}"})
        dirs.append({"path": "${root}/runtimes"})
        generated["manager.service"] = (
            "[Unit]\nAfter=network.target\n[Service]\nExecStart=${root}/releases/${release}/bin/gpu-node-manager --config-dir ${root}/runtimes --lock-path ${root}/config/transition.lock serve --host 127.0.0.1 --port ${PORT}\nRestart=on-failure\n[Install]\nWantedBy=multi-user.target\n"
        )
        base.update(
            kind="native",
            python="/usr/bin/python3.12",
            venv="${root}/releases/${release}",
            wheels=wheels,
            units=[{"name": app + ".web.service", "source": file("manager.service")}],
            health_url="http://127.0.0.1:${PORT}/api/status",
        )
    else:
        if "image.tar" not in files or "image_id" not in candidate:
            raise ValueError("Docker candidate must include its immutable archive and image ID")
        mounts = []
        base.update(
            kind="docker",
            image_archive=file("image.tar"),
            image_id=candidate["image_id"],
            container_name=app,
            environment_file="${root}/config/runtime.env",
            mounts=mounts,
        )
        copies.append(
            {
                "source": file("runtime.env", private=True),
                "destination": "${root}/config/runtime.env",
            }
        )
        env = []
        if app == "flamoris-generation-mcp":
            env = [
                "FLAMORIS_HTTP_HOST=127.0.0.1",
                "FLAMORIS_HTTP_PORT=${PORT}",
                "FLAMORIS_WORKFLOW_DIR=/data/workflows",
                "FLAMORIS_OUTPUT_DIR=/data/outputs",
            ]
            mounts.extend([data("workflows", "/data/workflows"), data("outputs", "/data/outputs")])
        elif app == "flamoris-intelligence-mcp":
            env = [
                "FLAMORIS_INTELLIGENCE_HTTP_HOST=127.0.0.1",
                "FLAMORIS_INTELLIGENCE_HTTP_PORT=${PORT}",
            ]
        elif app == "flamoris-mcp-hub":
            settings.append(
                setting(
                    "HUB_TOKEN", "Hub接続トークン", secret=True, generate=True, kind="url_password"
                )
            )
            env = [
                "FLAMORIS_MCP_HUB_PORT=${PORT}",
                "FLAMORIS_MCP_HUB_CONFIG_DIR=/app/config/mcps",
                "FLAMORIS_MCP_HUB_CLIENT_TOKEN=${HUB_TOKEN}",
            ]
            mounts.append(data("mcps", "/app/config/mcps", readonly=True))
            base["health_url"] = "http://127.0.0.1:${PORT}/mcp"
        elif app in {"flamoris-ai-agent", "flamoris-studio"}:
            settings.extend(
                [
                    setting(
                        "ADMIN_DSN", "PostgreSQL管理者の接続文字列", secret=True, required=True
                    ),
                    setting(
                        "PGHOST",
                        "PostgreSQLホスト（ホスト・コンテナ双方から到達可能）",
                        required=True,
                    ),
                    setting("PGPORT", "PostgreSQLポート", "5432", kind="port"),
                    setting(
                        "DATABASE",
                        "新しく作成するDB名",
                        "flamoris_ai" if app == "flamoris-ai-agent" else "flamoris_studio",
                        kind="name",
                    ),
                    setting(
                        "OWNER_PASSWORD",
                        "新規DB所有者パスワード（空欄で生成）",
                        secret=True,
                        generate=True,
                        kind="url_password",
                    ),
                    setting(
                        "RUNTIME_PASSWORD",
                        "アプリ用DBパスワード（空欄で生成）",
                        secret=True,
                        generate=True,
                        kind="url_password",
                    ),
                ]
            )
            for name, value in {
                "admin.dsn": "${ADMIN_DSN}",
                "owner.password": "${OWNER_PASSWORD}",
                "runtime.password": "${RUNTIME_PASSWORD}",
            }.items():
                generated[name] = value
            owner, runtime = (
                ("flamoris_ai_owner", "flamoris_ai_app")
                if app == "flamoris-ai-agent"
                else ("flamoris_studio_owner", "flamoris_studio_app")
            )
            db = {
                "name": "${DATABASE}",
                "admin_dsn": file("admin.dsn", private=True),
                "owner": owner,
                "runtime_role": runtime,
                "owner_password": file("owner.password", private=True),
                "runtime_password": file("runtime.password", private=True),
            }
            base["database"] = db
            if app == "flamoris-ai-agent":
                sql = [
                    name
                    for name in files
                    if name == "db/01_schema.sql"
                    or name.startswith("db/migrations/")
                    and name.endswith(".sql")
                ]
                if "db/01_schema.sql" not in sql:
                    raise ValueError("Agent candidate must include application-owned SQL")
                db["sql_files"] = [file(name) for name in sorted(sql)]
                settings.append(
                    setting(
                        "AGENT_TOKEN",
                        "Agentサービス接続トークン（空欄で生成）",
                        secret=True,
                        generate=True,
                        kind="url_password",
                    )
                )
                env = [
                    "AGENT_HTTP_HOST=127.0.0.1",
                    "AGENT_HTTP_PORT=${PORT}",
                    "AGENT_MCP_TOKEN=${AGENT_TOKEN}",
                    "PGHOST=${PGHOST}",
                    "PGPORT=${PGPORT}",
                    "PGDATABASE=${DATABASE}",
                    "PGUSER=" + runtime,
                    "PGPASSWORD=${RUNTIME_PASSWORD}",
                ]
            else:
                env = [
                    "STUDIO_DATABASE_URL=postgresql+psycopg://"
                    + runtime
                    + ":${RUNTIME_PASSWORD}@${PGHOST}:${PGPORT}/${DATABASE}",
                    "STUDIO_THUMBNAIL_DIR=/data/thumbnails",
                ]
                generated["migration.env"] = (
                    "STUDIO_DATABASE_URL=postgresql+psycopg://"
                    + owner
                    + ":${OWNER_PASSWORD}@${PGHOST}:${PGPORT}/${DATABASE}\n"
                )
                db["studio_migration_environment"] = file("migration.env", private=True)
                mounts.append(data("thumbnails", "/data/thumbnails"))
                base.update(
                    network="bridge",
                    ports=[{"host": {"setting_int": "PORT"}, "container": 5087}],
                    health_url="http://127.0.0.1:${PORT}/api/system/status",
                )
        else:
            raise ValueError("Unsupported FLAMORIS release")
        generated["runtime.env"] = "\n".join(env) + "\n"
    return Recipe.model_validate(
        {
            "application_id": app,
            "release": release,
            "platform": candidate["platform"],
            "compatible_from": candidate.get("compatible_from", []),
            "settings": settings,
            "downloads": downloads,
            "generated": generated,
            "application": base,
        }
    )


def build_catalog(candidates):
    return Catalog(
        catalog_version=1,
        recipes=[build_recipe(candidate, origin) for candidate, origin in candidates],
    )
