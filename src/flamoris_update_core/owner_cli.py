"""Application-owned local socket service, authenticated by OS peer credentials."""

import argparse
import os
import socket
import socketserver
import struct
from pathlib import Path

from pydantic import Field, model_validator

from .contracts import OwnerRequest
from .errors import UpdateError
from .local_transport import receive_exact
from .models import Model
from .owner import OwnerConfiguration
from .resources import protected_read
from .wire import decode, digest, dumps, loads


class ServerConfiguration(Model):
    owner: OwnerConfiguration
    socket_path: str
    socket_group_id: int = Field(ge=0)
    allowed_peer_uids: list[int] = Field(min_length=1, max_length=16)

    @model_validator(mode="after")
    def local(self):
        if not Path(self.socket_path).is_absolute() or any(u < 0 for u in self.allowed_peer_uids):
            raise ValueError("Absolute socket path and nonnegative peer UIDs are required")
        return self


def dispatch(owner, action, raw):
    if action == "/operations":
        return dumps(owner.perform(decode(OwnerRequest, raw)))
    if action != "/inspect":
        raise UpdateError("forbidden")
    obj = loads(raw)
    profile = owner.profile
    if (
        set(obj)
        != {"contract_version", "observation_id", "deployment_id", "resource_ids", "profile_digest"}
        or type(obj["contract_version"]) is not int
        or obj["contract_version"] != 1
        or obj["deployment_id"] != profile.id
        or obj["resource_ids"] != sorted(profile.resources.values())
        or obj["profile_digest"] != digest(dumps(profile))
    ):
        raise UpdateError("forbidden")
    # A fresh Owner has required nullable release/manifest fields. Preserve nulls.
    return dumps(owner.inspect(obj["observation_id"]).model_dump(mode="json"))


def serve_connection(connection, owner, allowed_peer_uids, guard):
    connection.settimeout(120)
    try:
        _, uid, _ = struct.unpack(
            "3i", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
        )
        if uid not in allowed_peer_uids:
            raise UpdateError("forbidden")
        size = struct.unpack("!I", receive_exact(connection, 4))[0]
        packet = loads(receive_exact(connection, size))
        # Consume the bounded frame before returning a policy error. Otherwise
        # closing with unread request bytes can turn a known rejection into a reset.
        guard()
        if set(packet) != {"action", "body"} or not isinstance(packet["action"], str):
            raise UpdateError("invalid_input")
        raw = dispatch(owner, packet["action"], dumps(packet["body"]))
    except Exception as error:
        raw = dumps(
            error.public() if isinstance(error, UpdateError) else {"error": "outcome_unknown"}
        )
    if len(raw) > 1024 * 1024:
        raw = dumps({"error": "quota_exceeded"})
    connection.sendall(struct.pack("!I", len(raw)) + raw)


def create_server(owner, cfg, guard):
    path = Path(cfg.socket_path)
    # Peers may traverse the socket directory but must not replace its entries.
    if (
        path.parent.is_symlink()
        or path.parent.stat().st_uid != os.geteuid()
        or path.parent.stat().st_mode & 0o027
        or path.exists()
        or path.is_symlink()
    ):
        raise UpdateError("unsafe_storage", "Provide an empty protected socket path")

    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            serve_connection(self.request, owner, cfg.allowed_peer_uids, guard)

    class Server(socketserver.UnixStreamServer):
        request_queue_size = 8

        def server_bind(self):
            # Binding and permissions happen before the socket begins listening.
            super().server_bind()
            self.socket_identity = path.stat().st_ino
            os.chown(path, os.geteuid(), cfg.socket_group_id)
            os.chmod(path, 0o660)

        def server_close(self):
            super().server_close()
            if path.is_socket() and path.stat().st_ino == getattr(self, "socket_identity", None):
                path.unlink()

        def handle_error(self, request, client_address):
            # Lost replies remain unknown; do not emit packets or credentials.
            pass

    return Server(str(path), Handler)


def serve(factory) -> None:
    parser = argparse.ArgumentParser(description="Application-owned Updater local socket service")
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    path = Path(args.config)
    try:
        raw = protected_read(path)
        cfg = decode(ServerConfiguration, raw)
        owner = factory(cfg.owner)
        expected = digest(raw)

        def guard():
            if digest(protected_read(path)) != expected:
                raise UpdateError("policy_changed")

        with create_server(owner, cfg, guard) as server:
            server.serve_forever()
    except (UpdateError, OSError, ValueError):
        parser.exit(1, "Owner startup failed; check local configuration and socket permissions.\n")
