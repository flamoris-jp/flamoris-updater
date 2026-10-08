"""Build the shared namespaces from one source tree, including sdist rebuilds."""

from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version, build_data):
        root = Path(self.root)
        source = root / "src"
        if not source.is_dir():
            source = root.parent.parent / "src"
        for package in ("flamoris_update_core", "flamoris_update_migration"):
            if not (source / package).is_dir():
                raise ValueError("Shared update source is missing")
            for path in sorted(
                [*(source / package).rglob("*.py"), *(source / package).glob("py.typed")]
            ):
                relative = path.relative_to(source).as_posix()
                target = relative if self.target_name == "wheel" else "src/" + relative
                build_data["force_include"][str(path)] = target
