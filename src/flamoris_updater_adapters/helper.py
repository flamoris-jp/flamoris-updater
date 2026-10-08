import argparse
import os
import socket
import struct
from pathlib import Path

from flamoris_update_core.errors import UpdateError
from flamoris_update_core.wire import dumps, loads

from .control import HostControl
from .journal import exclusive
from .runtime import executor
from .signing import open_packet
from .transport import receive_exact


class Dispatch:
    def __init__(self, host):
        self.host, self.control = host, HostControl(host)

    def invoke(self, packet):
        signature = packet.get("signature", {})
        identity = signature.get("key_id") if isinstance(signature, dict) else None
        key = self.host.authorities.get(identity) if isinstance(identity, str) else None
        if key is None or key.purpose not in {"authority", "controller"}:
            raise UpdateError("forbidden")
        payload = open_packet(packet, self.host.authorities, self.host.domain, key.purpose)
        if "ticket_version" in payload:
            return self.host.run(packet)
        self.host.guard()
        if payload.get("command") in HostControl.COMMANDS:
            return self.control.invoke(packet)
        base = {"command", "domain", "host_id", "epoch"}
        if (
            payload.get("domain") != self.host.domain
            or payload.get("host_id") != self.host.host_id
            or payload.get("epoch") != int(self.host.journal.meta("epoch"))
        ):
            raise UpdateError("stale_authority")
        command = payload.get("command")
        if command == "inspect" and set(payload) == base | {"deployment_id"}:
            return self.host.inspect(payload["deployment_id"]).model_dump()
        if command == "inspect_operation" and set(payload) == base | {"operation_id"}:
            return self.host.outcome(payload["operation_id"])
        if command == "abort_preparation":
            return self.host.abort(packet)
        raise UpdateError("invalid_input")


def serve_connection(connection, dispatch, allowed_uids):
    connection.settimeout(120)
    try:
        _, uid, _ = struct.unpack(
            "3i", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
        )
        if uid not in allowed_uids:
            raise UpdateError("forbidden")
        size = struct.unpack("!I", receive_exact(connection, 4))[0]
        result = dispatch.invoke(loads(receive_exact(connection, size)))
    except Exception as error:
        result = error.public() if isinstance(error, UpdateError) else {"error": "outcome_unknown"}
    raw = dumps(result)
    if len(raw) > 1024 * 1024:
        raw = dumps({"error": "quota_exceeded"})
    connection.sendall(struct.pack("!I", len(raw)) + raw)


def main():
    parser = argparse.ArgumentParser(description="Root-owned typed host execution helper")
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise SystemExit("Host helper requires its pre-provisioned root service")
    cfg, host = executor(args.config)
    path = Path(cfg.socket_path)
    if not path.is_absolute():
        raise SystemExit("Absolute protected socket path is required")
    if path.parent.is_symlink():
        raise SystemExit("Unsafe socket directory")
    path.parent.mkdir(parents=True, mode=0o710, exist_ok=True)
    os.chown(path.parent, 0, cfg.socket_group_id)
    if path.parent.stat().st_uid != 0 or path.parent.stat().st_mode & 0o027:
        raise SystemExit("Socket directory must be root-owned and not writable by peers")
    with exclusive(host.journal.directory / "helper.lock"):
        with exclusive(host.journal.directory / "executor.lock"):
            host.journal.recover_intents()
        if path.exists() or path.is_symlink():
            if not path.is_socket():
                raise SystemExit("Refusing to replace an unexpected socket path")
            path.unlink()
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
            listener.bind(str(path))
            # Host API peers traverse a root-owned socket directory via a provisioned ACL.
            os.chown(path, 0, cfg.socket_group_id)
            os.chmod(path, 0o660)
            listener.listen(16)
            dispatch = Dispatch(host)
            try:
                while True:
                    connection, _ = listener.accept()
                    with connection:
                        serve_connection(connection, dispatch, cfg.allowed_peer_uids)
            finally:
                path.unlink(missing_ok=True)
