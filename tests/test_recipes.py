import pytest

from flamoris_update_core.wire import digest, dumps, loads
from flamoris_updater_adapters.install import VERSIONS
from flamoris_updater_adapters.recipes import build_catalog, build_recipe


@pytest.mark.parametrize("application", VERSIONS)
def test_candidates_supply_portable_recipes_with_app_owned_initialization(application):
    files = {
        "image.tar": digest(b"image"),
        "db/01_schema.sql": digest(b"sql"),
        "db/migrations/002.sql": digest(b"migration"),
        "manager.whl": digest(b"wheel"),
    }
    candidate = {
        "application_id": application,
        "release": VERSIONS[application],
        "platform": "linux/amd64",
        "image_id": digest(b"image-id"),
        "files": files,
    }
    recipe = build_recipe(candidate, "https://releases.example.invalid/candidate")
    assert (
        loads(dumps(build_catalog([(candidate, "https://releases.example.invalid/candidate")])))[
            "catalog_version"
        ]
        == 1
    )
    assert not recipe.dependencies  # Optional app connections do not force an install group.
    assert all(not item.default for item in recipe.settings if item.secret)
    assert recipe.application["release"] == VERSIONS[application]
    if application in {"flamoris-studio", "flamoris-ai-agent"}:
        assert "ADMIN_DSN" in {s.key for s in recipe.settings}
        assert recipe.application["database"]
    assert "backup" not in recipe.application and "restore" not in recipe.application


def test_candidate_update_compatibility_is_explicit():
    candidate = {
        "application_id": "flamoris-generation-mcp",
        "release": "1.1.0",
        "platform": "linux/amd64",
        "image_id": digest(b"image-id"),
        "files": {"image.tar": digest(b"image")},
        "compatible_from": ["1.0.0"],
    }
    assert build_recipe(candidate, "https://releases.example.invalid").compatible_from == ["1.0.0"]
