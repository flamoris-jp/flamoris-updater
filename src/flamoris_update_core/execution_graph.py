from .errors import UpdateError


def validate_execution_graph(plan):
    """Host-enforced minimum graph; a signed plan cannot omit safety phases or barriers."""
    readonly = plan.action == "verify_recovery"
    required = (
        ["prepare", "validate", "release"]
        if readonly
        else [
            "prepare",
            "begin",
            "close_admission",
            "drain",
            "stop",
            "activate",
            "validate",
            "reopen_admission",
            "release",
        ]
    )
    by_operation = {}
    ancestors = {}
    for step in plan.steps:
        by_operation.setdefault(step.operation, []).append(step)
        ancestors[step.id] = set(step.predecessors).union(
            *(ancestors[x] for x in step.predecessors)
        )
    for operation in required:
        participants = [s.deployment_id for s in by_operation.get(operation, [])]
        if len(participants) != len(set(participants)) or set(participants) != set(plan.targets):
            raise UpdateError("invalid_input", "Safety phase coverage is incomplete")
    dependencies = (
        {"validate": {"prepare"}, "release": {"validate"}}
        if readonly
        else {
            "begin": {"prepare"},
            "close_admission": {"begin"},
            "drain": {"close_admission"},
            "stop": {"drain"},
            "snapshot": {"stop"},
            "restore_verify": {"snapshot"},
            "apply_step": {"restore_verify", "stop"},
            "initialize": {"restore_verify", "stop"},
            "restore": {"restore_verify", "stop"},
            "verify_restored_state": {"restore"},
            "activate": {
                "restore_verify",
                "apply_step",
                "initialize",
                "verify_restored_state",
                "stop",
            },
            "validate": {"activate"},
            "reopen_admission": {"validate"},
            "release": {"reopen_admission"},
            "prepare": set(),
        }
    )
    dependencies.setdefault("prepare", set())
    if readonly and set(by_operation) - set(required):
        raise UpdateError("forbidden")
    if not readonly:
        for operation in ["snapshot", "restore_verify"] + (
            ["restore", "verify_restored_state"] if plan.action == "recover" else []
        ):
            covered = {r for s in by_operation.get(operation, []) for r in s.resources}
            if covered != set(plan.resources):
                raise UpdateError("backup_unverified")
        if plan.action == "recover" and any(
            op in by_operation for op in ["apply_step", "initialize"]
        ):
            raise UpdateError("forbidden")
        if plan.action == "install" and {
            s.deployment_id for s in by_operation.get("initialize", [])
        } != set(plan.targets):
            raise UpdateError("not_empty")
    for step in plan.steps:
        if step.operation not in dependencies:
            raise UpdateError("forbidden")
        required_ids = {
            s.id for op in dependencies[step.operation] for s in by_operation.get(op, [])
        }
        if not required_ids <= ancestors[step.id]:
            raise UpdateError("invalid_input", "Required global barrier is missing")
