"""Catalog presentation and discovery from recorded release origins, never app names."""

from flamoris_update_core.errors import UpdateError
from flamoris_update_core.wire import digest

from .github_releases import release_location
from .self_update import SELF

OFFICIAL = "https://github.com/flamoris-jp/flamoris-updater/releases/latest/download/catalog.json"


def latest_catalog(url):
    try:
        owner, repo, _, _ = release_location(url)
        return f"https://github.com/{owner}/{repo}/releases/latest/download/catalog.json"
    except UpdateError:
        return None


def installed_sources(manager):
    """Resolve legacy records through their immutable recipe or matching registered snapshot."""
    result = {SELF: OFFICIAL}
    for app in manager.journal.list("managed_app"):
        application = app.get("application_id", app["id"])
        recipe = manager.journal.get("managed_recipe", app.get("job_id", ""))
        if recipe:
            origins = {latest_catalog(d["url"]) for d in recipe.get("downloads", {}).values()}
            if len(origins) == 1 and None not in origins:
                result[application] = origins.pop()
                continue
        matches = []
        for url in manager.sources():
            catalog = manager._source_catalog(url)
            if any(
                (r.application_id, r.release, r.platform)
                == (application, app.get("release"), manager.hardware())
                for r in catalog.recipes
            ):
                matches.append(latest_catalog(url) or url)
        if len(set(matches)) == 1:
            result[application] = matches[0]
    return result


def discover_sources(manager):
    removed = (manager.journal.get("manager_config", "removed_sources") or {}).get("urls", [])
    failures = []
    added = []
    for url in dict.fromkeys(installed_sources(manager).values()):
        if url in removed or url in manager.sources():
            continue
        try:
            manager.configure(url)
            added.append(url)
        except (UpdateError, ValueError) as error:
            code = error.code if isinstance(error, UpdateError) else "invalid_catalog"
            previous = manager.journal.get("manager_source_status", digest(url.encode())) or {}
            with manager.journal.transaction() as db:
                manager.journal.put(
                    "manager_source_status",
                    digest(url.encode()),
                    {"checked_at": previous.get("checked_at"), "error": code},
                    db,
                )
            failures.append(
                {
                    "url": url,
                    "error": code,
                }
            )
    return failures, added


def source_items(manager):
    result = []
    for url in manager.sources():
        status = manager.journal.get("manager_source_status", digest(url.encode())) or {}
        catalog = manager._source_catalog(url)
        result.append(
            {
                "url": url,
                "checked_at": status.get("checked_at"),
                "error": status.get("error"),
                "applications": sorted(
                    {r.application_id for r in catalog.recipes}
                    | ({SELF} if catalog.updater_releases else set())
                ),
            }
        )
    return result


def application_checks(manager):
    installed = installed_sources(manager)
    sources = source_items(manager)
    result = {}
    removed = (manager.journal.get("manager_config", "removed_sources") or {}).get("urls", [])
    for app in manager.application_ids():
        url = installed.get(app)
        matching = [s for s in sources if app in s["applications"]]
        if url is None and len(matching) == 1:
            url = matching[0]["url"]
        status = manager.journal.get("manager_source_status", digest(url.encode())) if url else None
        result[app] = {
            "url": url,
            "registered": url in manager.sources(),
            "suppressed": url in removed,
            "checked_at": (status or {}).get("checked_at"),
            "error": (status or {}).get("error"),
        }
    return result
