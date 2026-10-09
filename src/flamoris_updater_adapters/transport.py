from flamoris_update_core.errors import UpdateError
from flamoris_update_core.inventory import Observation
from flamoris_update_core.local_transport import UnixClient, receive_exact  # noqa: F401
from flamoris_update_core.wire import decode, dumps, loads


class HTTPHost:
    def __init__(self, host_id, domain, endpoint, signer, epoch):
        self.host_id, self.domain, self.client, self.signer, self.epoch = (
            host_id,
            domain,
            endpoint.client(),
            signer,
            epoch,
        )
        self.url = endpoint.url.rstrip("/")

    def _post(self, path, packet):
        raw = dumps(packet)
        if len(raw) > 1024 * 1024:
            raise UpdateError("quota_exceeded")
        try:
            with self.client.stream(
                "POST",
                self.url + path,
                content=raw,
                headers={"content-type": "application/json"},
                follow_redirects=False,
            ) as response:
                parts, size = [], 0
                for chunk in response.iter_bytes(chunk_size=64 * 1024):
                    size += len(chunk)
                    if size > 1024 * 1024:
                        raise UpdateError("outcome_unknown")
                    parts.append(chunk)
                result = loads(b"".join(parts))
                if response.status_code != 200 or "error" in result:
                    raise UpdateError(result.get("error", "outcome_unknown"))
                return result
        except UpdateError:
            raise
        except Exception:
            raise UpdateError("outcome_unknown", "Host response is unavailable") from None

    def command(self, command, **arguments):
        return self.signer.packet(
            {
                "command": command,
                "domain": self.domain,
                "host_id": self.host_id,
                "epoch": self.epoch(),
                **arguments,
            }
        )

    def inspect(self, deployment_id):
        return decode(
            Observation,
            dumps(
                self._post(
                    "/api/v1/deployments/inspect",
                    self.command("inspect", deployment_id=deployment_id),
                )
            ),
            256 * 1024,
        )

    def run(self, packet):
        return self._post("/api/v1/operations/run", packet)

    def abort(self, packet):
        return self._post("/api/v1/preparations/abort", packet)

    def outcome(self, operation_id):
        return self._post(
            "/api/v1/operations/inspect",
            self.command("inspect_operation", operation_id=operation_id),
        )

    def protected(self, packet):
        return self._post("/api/v1/controller", packet)
