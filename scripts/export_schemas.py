import argparse
import json
from pathlib import Path

from flamoris_update_core.contracts import OwnerRequest, OwnerResult
from flamoris_update_core.inventory import DeploymentProfile, Observation, Resource
from flamoris_update_core.models import Manifest, Plan
from flamoris_update_core.owner_cli import ServerConfiguration
from flamoris_updater_adapters.config import (
    CoordinatorConfig,
    HelperConfig,
    HostAPIConfig,
    RecoveryConfig,
)
from flamoris_updater_adapters.inputs import TOOLS
from flamoris_updater_adapters.releases import Catalog


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    root = Path(args.output)
    root.mkdir(parents=True, exist_ok=True)
    for model in [
        Manifest,
        Plan,
        OwnerRequest,
        OwnerResult,
        DeploymentProfile,
        Observation,
        Resource,
        Catalog,
        CoordinatorConfig,
        HelperConfig,
        HostAPIConfig,
        RecoveryConfig,
        ServerConfiguration,
    ]:
        (root / (model.__name__ + ".schema.json")).write_text(
            json.dumps(model.model_json_schema(by_alias=True), indent=2) + "\n"
        )
    (root / "mcp-tools.schema.json").write_text(
        json.dumps(
            {name: model.model_json_schema() for name, (model, _, _) in TOOLS.items()}, indent=2
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
