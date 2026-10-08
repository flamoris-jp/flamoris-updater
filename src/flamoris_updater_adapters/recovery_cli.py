import argparse
import sys
from pathlib import Path

from flamoris_update_core.errors import UpdateError
from flamoris_update_core.wire import dumps, loads

from .compatibility import inspect_control
from .config import RecoveryConfig, load, signer
from .journal import inspect_journal
from .recovery import RecoveryController
from .runtime import coordinator


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Stable outage-independent inspector and protected recovery controller"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("inspect", "compatible"):
        p = commands.add_parser(name)
        p.add_argument("--state", required=True)
    for name in ("recover", "verify", "self-update", "resume-coordinator"):
        p = commands.add_parser(name)
        p.add_argument("--config", required=True)
        p.add_argument("--operator", required=True)
        p.add_argument("--request-key", required=True)
        if name in {"recover", "verify"}:
            p.add_argument("--parent-job", required=True)
            p.add_argument("--targets-file", required=True)
        if name == "self-update":
            p.add_argument("--target-manifest", required=True)
        if name != "resume-coordinator":
            p.add_argument(
                "--approve-plan-digest",
                help="Omit to prepare a reviewable plan; pass its exact digest to authorize",
            )
    args = parser.parse_args(argv)
    try:
        if args.command in {"inspect", "compatible"}:
            result = (
                inspect_journal(Path(args.state))
                if args.command == "inspect"
                else inspect_control(args.state)
            )
        else:
            cfg = load(RecoveryConfig, args.config)
            _, c, _ = coordinator(cfg.coordinator_config_file)
            signing = signer(cfg.controller_signer_id, cfg.controller_private_file)
            for host in c.hosts.values():
                host.signer = signing
            control = RecoveryController(
                c, signing, cfg.control_deployment_id, cfg.current_control_manifest, cfg.readiness
            )
            if args.command == "self-update":
                result = control.self_update(
                    args.operator, args.target_manifest, args.request_key, args.approve_plan_digest
                )
            elif args.command == "resume-coordinator":
                result = control.resume(args.operator, args.request_key)
            else:
                result = control.recover(
                    args.operator,
                    args.parent_job,
                    loads(Path(args.targets_file).read_bytes()),
                    args.request_key,
                    args.command == "verify",
                    args.approve_plan_digest,
                )
        sys.stdout.buffer.write(dumps(result) + b"\n")
    except Exception as error:
        sys.stderr.write(
            dumps(
                error.public()
                if isinstance(error, UpdateError)
                else {
                    "error": "outcome_unknown",
                    "message": "Inspect stable journals; no uncertain operation is retried",
                }
            ).decode()
            + "\n"
        )
        raise SystemExit(1) from None
