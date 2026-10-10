"""Optional GitHub Release access using operator-owned GitHub credentials."""

import json
import os
import pwd
import re
import subprocess
from urllib.parse import quote, unquote, urlsplit

from flamoris_update_core.errors import UpdateError

from .artifacts import Fetcher


def credential():
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        command = ["/usr/bin/gh", "auth", "token", "--hostname", "github.com"]
        environment = dict(os.environ)
        user = os.environ.get("FLAMORIS_GITHUB_USER")
        if user:
            try:
                account = pwd.getpwnam(user)
            except KeyError:
                return None
            if account.pw_uid == 0:
                return None
            if os.geteuid() == 0:
                command = ["/usr/sbin/runuser", "--user", user, "--", *command]
            elif account.pw_uid != os.geteuid():
                return None
            environment = {"PATH": "/usr/bin:/bin", "HOME": account.pw_dir}
        try:
            result = subprocess.run(
                command, capture_output=True, timeout=15, check=False, cwd="/", env=environment
            )
            if result.returncode:
                return None
            token = result.stdout.decode("ascii").strip()
        except (OSError, subprocess.TimeoutExpired, UnicodeError):
            return None
    return token if re.fullmatch(r"[!-~]{1,8192}", token) else None


def release_location(url):
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "github.com"
        or parsed.port not in (None, 443)
        or parsed.query
        or parsed.fragment
        or parsed.username
        or parsed.password
    ):
        raise UpdateError("release_unavailable")
    match = re.fullmatch(
        r"/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/releases/"
        r"(?:download/([^/]+)|latest/download)/([^/]+)",
        parsed.path,
    )
    if not match:
        raise UpdateError("release_unavailable")
    owner, repo, tag, name = match.groups()
    tag, name = unquote(tag) if tag else None, unquote(name)
    if (
        any(
            value and (len(value) > 1024 or any(c.isspace() or ord(c) < 32 for c in value))
            for value in (owner, repo, tag, name)
        )
        or any(
            segment in {"", ".", ".."}
            for value in (owner, repo, tag or "latest", name)
            for segment in value.split("/")
        )
        or "/" in name
        or "\\" in name
        or (tag and "\\" in tag)
    ):
        raise UpdateError("untrusted_origin")
    return owner, repo, tag, name


def positive_id(value):
    if type(value) is not int or value <= 0:
        raise UpdateError("release_unavailable")
    return value


def private_chunks(client, url, limit):
    owner, repo, tag, name = release_location(url)
    token = credential()
    if not token:
        raise UpdateError("github_access_required", "GitHub Release read access is required")
    base = f"https://api.github.com/repos/{owner}/{repo}/releases"
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}

    def metadata(location):
        fetcher = Fetcher([location], client, public_redirects=True)
        raw = b"".join(fetcher._chunks(location, 4 * 1024 * 1024, headers, api_token=token))
        return json.loads(raw)

    try:
        release = metadata(base + ("/tags/" + quote(tag, safe="") if tag else "/latest"))
        release_id = positive_id(release["id"])
        if release.get("draft") or (tag and release["tag_name"] != tag):
            raise UpdateError("release_unavailable")
        for page in range(1, 11):
            assets = metadata(f"{base}/{release_id}/assets?per_page=100&page={page}")
            if not isinstance(assets, list) or len(assets) > 100:
                raise UpdateError("release_unavailable")
            matches = [asset for asset in assets if asset["name"] == name]
            if len(matches) > 1:
                raise UpdateError("release_unavailable")
            if matches:
                asset = matches[0]
                asset_id = positive_id(asset["id"])
                if asset["state"] != "uploaded":
                    raise UpdateError("release_unavailable")
                if type(asset["size"]) is not int or not 0 <= asset["size"] <= limit:
                    raise UpdateError("quota_exceeded")
                location = f"{base}/assets/{asset_id}"
                fetcher = Fetcher([location], client, public_redirects=True)
                yield from fetcher._chunks(
                    location,
                    limit,
                    {**headers, "Accept": "application/octet-stream"},
                    api_token=token,
                    api_asset=True,
                )
                return
            if len(assets) < 100:
                break
    except (KeyError, TypeError, ValueError):
        raise UpdateError("release_unavailable", "GitHub Release metadata is invalid") from None
    raise UpdateError("release_unavailable")
