"""One-time operator maintenance for the already-configured 1.0.3 catalog."""

import argparse
import os
import stat
import subprocess
import sys
from pathlib import Path

URL = "https://raw.githubusercontent.com/flamoris-jp/flamoris-updater/main/catalogs/flamoris-20261011.json"
DIGEST = "sha256:283913682218ed78f24e641c102b7fc744156dad4fe21dfc107f139d65d4861f"


def bind(manager, catalog, *, check=False):
    from flamoris_update_core.errors import UpdateError
    from flamoris_update_core.wire import digest, dumps
    from flamoris_updater_adapters.managed import Recipe
    from flamoris_updater_adapters.self_update import SELF

    with manager.journal.transaction() as db:
        current = manager.journal.get("self_installation", "current", db)
        if not current or current["release"] != "1.0.3" or current["phase"] != "succeeded":
            raise UpdateError("unsupported_migration", "Requires an idle installed 1.0.3")
        if db.execute(
            "SELECT 1 FROM records WHERE kind='managed_job' AND "
            "COALESCE(json_extract(payload,'$.phase'),'unknown') NOT IN ('succeeded','failed') LIMIT 1"
        ).fetchone():
            raise UpdateError("busy", "Resolve existing Jobs before catalog maintenance")
        bindings = []
        for recipe in [*catalog.recipes, *catalog.updater_releases]:
            identity = digest(
                dumps(
                    dict(
                        application_id=recipe.application_id
                        if isinstance(recipe, Recipe)
                        else SELF,
                        release=recipe.release,
                        platform=recipe.platform
                        if isinstance(recipe, Recipe)
                        else recipe.artifact.platform,
                    )
                )
            )
            binding = digest(dumps(recipe))
            previous = manager.journal.get("catalog_recipe", identity, db)
            if previous and previous["digest"] != binding:
                raise UpdateError("operation_conflict", "Published releases must be immutable")
            bindings.append((identity, binding))
        if not check:
            for identity, binding in bindings:
                manager.journal.put("catalog_recipe", identity, {"digest": binding}, db)
            manager.journal.put("manager_catalog", "current", catalog.model_dump(), db)
            manager.journal.put("manager_config", "source", {"url": URL}, db)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--runtime", type=Path, required=True, help="Original installed 1.0.3 bundle"
    )
    parser.add_argument("--config", required=True, help="Existing absolute setup.json")
    parser.add_argument(
        "--check", action="store_true", help="Validate without changing catalog records"
    )
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error("Run with the existing root operator authority")
    vendor = args.runtime / "site-packages"
    if not vendor.is_absolute() or ".." in vendor.parts:
        parser.error("Runtime must be an absolute protected installed path")
    for item in [vendor, *vendor.parents]:
        info = item.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            parser.error(
                "Runtime ancestors must be root-owned, non-symlink and not writable by others"
            )
    sys.path.insert(0, str(vendor))
    from importlib.metadata import version

    from flamoris_update_core.wire import decode, digest
    from flamoris_updater_adapters.config import protected_read
    from flamoris_updater_adapters.journal import exclusive
    from flamoris_updater_adapters.managed import Catalog, Manager
    from flamoris_updater_adapters.setup import BootstrapConfig

    if version("flamoris-updater") != "1.0.3":
        parser.error("Select the original 1.0.3 runtime")
    cfg = decode(BootstrapConfig, protected_read(args.config, root_only=True))
    if not cfg.bootstrap_executable or Path(cfg.bootstrap_executable).parent.parent != args.runtime:
        parser.error("Runtime must match the existing pinned bootstrap configuration")
    state = Path(cfg.helper_state_directory)
    if not (state / "journal.sqlite").is_file():
        parser.error("Existing manager journal required; do not bootstrap a new state")
    if not args.check:
        for unit in ("flamoris-updater-manager.service", "flamoris-updater-supervisor.service"):
            result = subprocess.run(
                ["systemctl", "show", "--property=ActiveState", "--value", unit],
                capture_output=True,
                text=True,
                check=True,
            )
            if result.stdout.strip() != "inactive":
                parser.error("Stop both idle manager and supervisor before switching the catalog")
    manager = Manager(state, Path(cfg.root))
    try:
        raw = manager._download(URL, 1024 * 1024)
        if digest(raw) != DIGEST:
            parser.error("Published snapshot digest mismatch")
        catalog = decode(Catalog, raw)
        with exclusive(state / "manager.lock"):
            bind(manager, catalog, check=args.check)
        print(
            "Catalog validated; no records changed"
            if args.check
            else "Catalog switched; restart original services and select 1.0.4"
        )
    finally:
        manager.client.close()


if __name__ == "__main__":
    main()
