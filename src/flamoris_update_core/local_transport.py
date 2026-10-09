"""Bounded local IPC with Linux OS peer credentials; no network certificates."""

import socket
import struct

from .errors import UpdateError
from .wire import dumps, loads


def receive_exact(connection, length):
    if not 0 <= length <= 1024 * 1024:
        raise UpdateError("quota_exceeded")
    parts = []
    while length:
        part = connection.recv(min(length, 64 * 1024))
        if not part:
            raise UpdateError("outcome_unknown")
        parts.append(part)
        length -= len(part)
    return b"".join(parts)


class UnixClient:
    def __init__(self, path: str, timeout=120, expected_uid=0):
        self.path, self.timeout, self.expected_uid = path, timeout, expected_uid

    def call(self, packet):
        raw = dumps(packet)
        if len(raw) > 1024 * 1024:
            raise UpdateError("quota_exceeded")
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.settimeout(self.timeout)
                connection.connect(self.path)
                _, uid, _ = struct.unpack(
                    "3i", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
                )
                if uid != self.expected_uid:
                    raise UpdateError("forbidden")
                connection.sendall(struct.pack("!I", len(raw)) + raw)
                size = struct.unpack("!I", receive_exact(connection, 4))[0]
                result = loads(receive_exact(connection, size))
                if "error" in result:
                    raise UpdateError(result["error"])
                return result
        except (OSError, TimeoutError):
            raise UpdateError("outcome_unknown", "Local response is unavailable") from None
