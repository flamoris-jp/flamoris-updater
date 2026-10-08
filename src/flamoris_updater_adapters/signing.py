import base64
import binascii
from dataclasses import dataclass

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from flamoris_update_core.errors import UpdateError
from flamoris_update_core.wire import digest, dumps, loads


@dataclass(frozen=True)
class Key:
    public: bytes
    application: str
    purpose: str
    revoked: bool = False


class Signer:
    def __init__(self, identity: str, private: bytes):
        self.identity = identity
        self.private = Ed25519PrivateKey.from_private_bytes(private)

    @property
    def public(self) -> bytes:
        return self.private.public_key().public_bytes_raw()

    def envelope(self, data: bytes) -> dict:
        return {
            "signature_version": 1,
            "algorithm": "ed25519",
            "key_id": self.identity,
            "manifest_sha256": digest(data),
            "signature": base64.b64encode(self.private.sign(data)).decode("ascii"),
        }

    def packet(self, payload: dict) -> dict:
        data = dumps(payload)
        return {"payload": base64.b64encode(data).decode("ascii"), "signature": self.envelope(data)}


def verify(
    data: bytes, envelope: bytes | dict, keys: dict[str, Key], application: str, purpose: str
) -> str:
    obj = loads(envelope, 16 * 1024) if isinstance(envelope, bytes) else envelope
    fields = {"signature_version", "algorithm", "key_id", "manifest_sha256", "signature"}
    if (
        not isinstance(obj, dict)
        or set(obj) != fields
        or type(obj["signature_version"]) is not int
        or obj["signature_version"] != 1
        or obj["algorithm"] != "ed25519"
        or not isinstance(obj["key_id"], str)
        or not isinstance(obj["signature"], str)
        or obj["manifest_sha256"] != digest(data)
    ):
        raise UpdateError("untrusted_release")
    key = keys.get(obj["key_id"])
    if key is None or key.revoked or key.application != application or key.purpose != purpose:
        raise UpdateError("untrusted_release")
    try:
        signature = base64.b64decode(obj["signature"], validate=True)
        if len(signature) != 64:
            raise ValueError("signature length")
        Ed25519PublicKey.from_public_bytes(key.public).verify(signature, data)
    except (ValueError, TypeError, InvalidSignature, binascii.Error):
        raise UpdateError("untrusted_release") from None
    return obj["key_id"]


def open_packet(packet: dict, keys: dict[str, Key], domain: str, purpose: str) -> dict:
    if not isinstance(packet, dict) or set(packet) != {"payload", "signature"}:
        raise UpdateError("invalid_input")
    try:
        data = base64.b64decode(packet["payload"], validate=True)
    except (ValueError, TypeError):
        raise UpdateError("invalid_input") from None
    if len(data) > 1024 * 1024:
        raise UpdateError("invalid_input")
    verify(data, packet["signature"], keys, domain, purpose)
    return loads(data)
