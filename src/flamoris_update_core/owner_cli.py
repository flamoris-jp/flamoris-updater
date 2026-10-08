"""A separate bounded mTLS owner endpoint; never served by the product UI."""

import argparse
import hashlib
import ssl
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from pydantic import Field

from .contracts import OwnerRequest
from .errors import UpdateError
from .models import Digest, Model
from .owner import OwnerConfiguration
from .resources import protected_read
from .wire import decode, digest, dumps, loads


class ServerConfiguration(Model):
    owner: OwnerConfiguration
    listen_host: str = "127.0.0.1"
    listen_port: int = Field(gt=0, lt=65536)
    ca_file: str
    cert_file: str
    key_file: str
    allowed_client_sha256: list[Digest] = Field(min_length=1, max_length=16)


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
    return dumps(owner.inspect(obj["observation_id"]))


def serve(factory) -> None:
    parser = argparse.ArgumentParser(description="Application-owned Updater endpoint (mTLS)")
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    path = Path(args.config)
    try:
        raw = protected_read(path)
        cfg = decode(ServerConfiguration, raw)
        owner = factory(cfg.owner)
        files = [
            (path, False),
            (Path(cfg.ca_file), False),
            (Path(cfg.cert_file), False),
            (Path(cfg.key_file), True),
        ]
        expected = {str(p): digest(protected_read(p, private=private)) for p, private in files}

        def guard():
            if any(
                digest(protected_read(p, private=private)) != expected[str(p)]
                for p, private in files
            ):
                raise UpdateError("policy_changed")

        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.verify_mode = ssl.CERT_REQUIRED
        context.load_verify_locations(cafile=cfg.ca_file)
        context.load_cert_chain(cfg.cert_file, cfg.key_file)

        class Server(ThreadingHTTPServer):
            daemon_threads = True
            request_queue_size = 8
            slots = threading.BoundedSemaphore(8)

            def get_request(self):
                sock, address = super().get_request()
                try:
                    sock.settimeout(5)
                    return context.wrap_socket(sock, server_side=True), address
                except BaseException:
                    sock.close()
                    raise

            def process_request(self, request, address):
                if not self.slots.acquire(blocking=False):
                    request.close()
                    return
                try:
                    super().process_request(request, address)
                except BaseException:
                    self.slots.release()
                    raise

            def process_request_thread(self, request, address):
                try:
                    super().process_request_thread(request, address)
                finally:
                    self.slots.release()

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_POST(self):
                try:
                    guard()
                    peer = self.connection.getpeercert(binary_form=True)
                    if (
                        "sha256:" + hashlib.sha256(peer).hexdigest()
                        not in cfg.allowed_client_sha256
                    ):
                        raise UpdateError("forbidden")
                    values = self.headers.get_all("Content-Length", [])
                    if (
                        len(values) != 1
                        or not values[0].isdigit()
                        or self.headers.get("Transfer-Encoding")
                    ):
                        raise UpdateError("invalid_input")
                    size = int(values[0])
                    if size > 1024 * 1024:
                        raise UpdateError("invalid_input")
                    body = self.rfile.read(size)
                    if len(body) != size:
                        raise UpdateError("invalid_input")
                    result, status = dispatch(owner, self.path, body), 200
                except UpdateError as error:
                    result, status = dumps({"error": error.code}), 409
                except Exception:
                    result, status = dumps({"error": "outcome_unknown"}), 500
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(result)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(result)

        with Server((cfg.listen_host, cfg.listen_port), Handler) as server:
            server.serve_forever()
    except (UpdateError, OSError, ValueError):
        parser.exit(1, "Owner startup failed; check protected configuration locally.\n")
