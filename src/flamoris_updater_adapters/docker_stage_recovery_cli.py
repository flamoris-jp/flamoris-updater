"""Run with a reviewed Updater runtime, after stopping its observed services."""

import argparse
import json
import re

from flamoris_update_core.wire import decode
from flamoris_updater_adapters.config import protected_read
from flamoris_updater_adapters.docker_stage_recovery import recover
from flamoris_updater_adapters.install import run
from flamoris_updater_adapters.managed import Manager
from flamoris_updater_adapters.setup import BootstrapConfig


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--setup", required=True)
    parser.add_argument("--job", required=True)
    parser.add_argument("--web-unit", required=True)
    parser.add_argument("--manager-unit", required=True)
    parser.add_argument("--supervisor-unit", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch(r"job-[0-9a-f]{32}", args.job):
        parser.error("Supply the exact managed Job ID")
    units = (args.web_unit, args.manager_unit, args.supervisor_unit)
    if set(units) != {
        "flamoris-updater.service",
        "flamoris-updater-manager.service",
        "flamoris-updater-supervisor.service",
    }:
        parser.error("Supply the three observed Updater service names")
    for unit in units:
        loaded = run(
            ["/usr/bin/systemctl", "show", unit, "--property=LoadState", "--value"]
        ).strip()
        if loaded != b"loaded":
            parser.error("Each supplied service must exist")
        active = run(
            ["/usr/bin/systemctl", "show", unit, "--property=ActiveState", "--value"]
        ).strip()
        if active != b"inactive":
            parser.error("All three Updater services must be inactive")
    cfg = decode(BootstrapConfig, protected_read(args.setup, private=True))
    manager = Manager(cfg.helper_state_directory, cfg.root, self_configuration=cfg)
    print(json.dumps(recover(manager, args.job, apply=args.apply)))


if __name__ == "__main__":
    main()
