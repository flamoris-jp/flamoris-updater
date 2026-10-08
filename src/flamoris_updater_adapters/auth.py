import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError

from flamoris_update_core.errors import UpdateError


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class AuthStore:
    def __init__(self, journal, authority, clock):
        self.journal, self.authority, self.clock = journal, authority, clock
        self.hasher = PasswordHasher()
        self.dummy = self.hasher.hash(secrets.token_urlsafe(32))

    def user(self, username: str, password: str, roles: list[str], targets: list[str]):
        if not 1 <= len(username) <= 128 or not 12 <= len(password) <= 1024:
            raise UpdateError(
                "invalid_input", "Use a nonempty username and a password of at least 12 characters"
            )
        import re

        if re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,127}", username) is None:
            raise UpdateError("invalid_input")
        self.authority.provision(username, roles, targets)
        with self.journal.transaction() as db:
            if self.journal.meta("mode", db) != "active":
                raise UpdateError("busy")
            self.journal.put("user", username, {"password_hash": self.hasher.hash(password)}, db)
            self.journal.event(db, "user_provisioned", username)

    def issue_token(self, subject: str, lifetime: int = 86400) -> str:
        self.authority.require(subject, "read", [])
        if not 60 <= lifetime <= 30 * 86400:
            raise UpdateError("invalid_input")
        token = secrets.token_urlsafe(48)
        with self.journal.transaction() as db:
            if self.journal.meta("mode", db) != "active":
                raise UpdateError("busy")
            self.journal.put(
                "token",
                token_hash(token),
                {"subject": subject, "expires_at": self.clock() + lifetime, "revoked": False},
                db,
            )
            self.journal.event(db, "token_issued", subject)
        return token

    def revoke_token(self, subject: str, token: str):
        identity = token_hash(token)
        with self.journal.transaction() as db:
            if self.journal.meta("mode", db) != "active":
                raise UpdateError("busy")
            record = self.journal.get("token", identity, db)
            if record is None or record["subject"] != subject:
                raise UpdateError("forbidden")
            self.journal.put("token", identity, {**record, "revoked": True}, db)
            self.journal.event(db, "token_revoked", subject)

    def disable_user(self, subject: str):
        principal = self.journal.get("principal", subject)
        if principal is None:
            raise UpdateError("forbidden")
        self.authority.provision(subject, principal["roles"], principal["targets"], active=False)

    def bearer(self, token: str) -> str:
        if not isinstance(token, str) or not 16 <= len(token) <= 256:
            raise UpdateError("unauthorized")
        record = self.journal.get("token", token_hash(token))
        if record is None or record["revoked"] or record["expires_at"] <= self.clock():
            raise UpdateError("unauthorized")
        self.authority.require(record["subject"], "read", [])
        return record["subject"]

    def login(self, username: str, password: str, remote: str):
        if (
            not isinstance(username, str)
            or not isinstance(password, str)
            or len(username) > 128
            or len(password) > 1024
        ):
            raise UpdateError("unauthorized")
        identities = ["account-" + token_hash(username), "peer-" + token_hash(remote)]
        with self.journal.transaction() as db:
            if self.journal.meta("mode", db) != "active":
                raise UpdateError("busy")
            db.execute(
                "DELETE FROM records WHERE kind='login_rate' AND json_extract(payload, '$.until') <= ?",
                (self.clock(),),
            )
            if (
                db.execute("SELECT COUNT(*) FROM records WHERE kind='login_rate'").fetchone()[0]
                >= 16384
            ):
                raise UpdateError("rate_limited")
            for identity in identities:
                rate = self.journal.get("login_rate", identity, db)
                if rate and rate["until"] > self.clock() and rate["attempts"] >= 5:
                    raise UpdateError("rate_limited")
                self.journal.put(
                    "login_rate",
                    identity,
                    {
                        "until": rate["until"]
                        if rate and rate["until"] > self.clock()
                        else self.clock() + 300,
                        "attempts": rate["attempts"] + 1
                        if rate and rate["until"] > self.clock()
                        else 1,
                    },
                    db,
                )
        user = self.journal.get("user", username)
        try:
            valid = self.hasher.verify(user["password_hash"] if user else self.dummy, password)
        except VerificationError:
            valid = False
        if not valid or user is None:
            raise UpdateError("unauthorized")
        session, csrf = secrets.token_urlsafe(48), secrets.token_urlsafe(32)
        with self.journal.transaction() as db:
            if self.journal.meta("mode", db) != "active":
                raise UpdateError("busy")
            principal = self.authority.require(username, "read", [], db)
            current_user = self.journal.get("user", username, db)
            if current_user["_revision"] != user["_revision"]:
                raise UpdateError("unauthorized")
            self.journal.put(
                "session",
                token_hash(session),
                {
                    "subject": username,
                    "principal_revision": principal["_revision"],
                    "expires_at": self.clock() + 3600,
                    "csrf": csrf,
                    "revoked": False,
                },
                db,
            )
            self.journal.event(db, "web_login", username)
        return session, csrf

    def session(self, token: str):
        if not isinstance(token, str) or not 16 <= len(token) <= 256:
            raise UpdateError("unauthorized")
        record = self.journal.get("session", token_hash(token))
        if record is None or record["revoked"] or record["expires_at"] <= self.clock():
            raise UpdateError("unauthorized")
        principal = self.authority.require(record["subject"], "read", [])
        if principal["_revision"] != record["principal_revision"]:
            raise UpdateError("unauthorized")
        return record

    def logout(self, token: str):
        with self.journal.transaction() as db:
            record = self.journal.get("session", token_hash(token), db)
            if record:
                self.journal.put("session", token_hash(token), {**record, "revoked": True}, db)
                self.journal.event(db, "web_logout", record["subject"])
