import gzip
import hashlib
import os
import shutil
import tarfile
import tempfile
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

import httpx

from flamoris_update_core.errors import UpdateError
from flamoris_update_core.wire import digest, loads


def relative(name: str) -> str:
    if (
        not isinstance(name, str)
        or not name
        or len(name) > 1024
        or "\\" in name
        or "\x00" in name
        or PurePosixPath(name).is_absolute()
        or any(x in {"", ".", ".."} for x in name.split("/"))
    ):
        raise UpdateError("unsafe_artifact", "Unconfined artifact member")
    return name


def origin(url: str) -> str:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        raise UpdateError("untrusted_origin")
    try:
        hostname = parsed.hostname.lower()
        hostname = "[" + hostname + "]" if ":" in hostname else hostname
        return "https://" + hostname + (":" + str(parsed.port) if parsed.port else "")
    except ValueError:
        raise UpdateError("untrusted_origin") from None


class Fetcher:
    def __init__(self, origins: list[str], client: httpx.Client):
        self.origins = {origin(x) for x in origins}
        self.client = client

    def chunks(self, url: str, limit: int, headers=None):
        if origin(url) not in self.origins or any(
            x in {".", ".."} for x in unquote(urlsplit(url).path).split("/")
        ):
            raise UpdateError("untrusted_origin")
        try:
            with self.client.stream(
                "GET", url, headers=headers or {}, follow_redirects=False
            ) as response:
                if response.status_code != 200:
                    raise UpdateError("release_unavailable")
                declared = response.headers.get("content-length")
                if declared and (not declared.isdecimal() or int(declared) > limit):
                    raise UpdateError("quota_exceeded")
                used = 0
                for chunk in response.iter_bytes(chunk_size=64 * 1024):
                    used += len(chunk)
                    if used > limit:
                        raise UpdateError("quota_exceeded")
                    yield chunk
        except httpx.HTTPError:
            raise UpdateError("release_unavailable", "Approved release fetch failed") from None

    def bytes(self, url: str, limit: int, headers=None) -> bytes:
        return b"".join(self.chunks(url, limit, headers))


class BoundedReader:
    def __init__(self, source, budget: int):
        self.source, self.remaining = source, budget

    def read(self, size=-1):
        if size < 0 or size > 1024 * 1024:
            raise UpdateError("quota_exceeded")
        result = self.source.read(min(size, self.remaining + 1))
        self.remaining -= len(result)
        if self.remaining < 0:
            raise UpdateError("quota_exceeded")
        return result


class NativeStore:
    def __init__(
        self,
        root: Path,
        fetcher: Fetcher,
        max_download=1024 * 1024 * 1024,
        max_expanded=4 * 1024 * 1024 * 1024,
        max_files=10000,
        reserve=64 * 1024 * 1024,
    ):
        self.root, self.fetcher = Path(root), fetcher
        self.max_download, self.max_expanded, self.max_files, self.reserve = (
            max_download,
            max_expanded,
            max_files,
            reserve,
        )
        if self.root.is_symlink():
            raise UpdateError("unsafe_storage")
        self.root.mkdir(parents=True, mode=0o755, exist_ok=True)
        if self.root.stat().st_uid != os.geteuid() or self.root.stat().st_mode & 0o022:
            raise UpdateError("unsafe_storage")

    def prepare(self, artifact) -> Path:
        if artifact.kind != "native":
            raise UpdateError("unsupported_platform")
        destination = self.root / artifact.digest.removeprefix("sha256:")
        if destination.exists():
            self.verify(destination, artifact)
            return destination
        if (
            artifact.max_expanded_bytes > self.max_expanded
            or shutil.disk_usage(self.root).free
            < self.reserve + self.max_download + artifact.max_expanded_bytes
        ):
            raise UpdateError("quota_exceeded")
        with tempfile.TemporaryDirectory(prefix=".prepare-", dir=self.root) as directory:
            temporary = Path(directory)
            archive_path = temporary / "download"
            hasher = hashlib.sha256()
            with archive_path.open("xb") as stream:
                for chunk in self.fetcher.chunks(artifact.locator, self.max_download):
                    stream.write(chunk)
                    hasher.update(chunk)
                stream.flush()
                os.fsync(stream.fileno())
            if "sha256:" + hasher.hexdigest() != artifact.digest:
                raise UpdateError("untrusted_release")
            tree = temporary / "tree"
            tree.mkdir(mode=0o700)
            members, total = set(), 0
            try:
                with archive_path.open("rb") as source:
                    magic = source.read(2)
                    source.seek(0)
                    expanded = gzip.GzipFile(fileobj=source) if magic == b"\x1f\x8b" else source
                    reader = BoundedReader(
                        expanded,
                        artifact.max_expanded_bytes + self.max_files * 1024 + 2 * 1024 * 1024,
                    )
                    with tarfile.open(fileobj=reader, mode="r|") as archive:
                        for member in archive:
                            name = relative(
                                member.name.rstrip("/") if member.isdir() else member.name
                            )
                            if (
                                name in members
                                or len(members) >= self.max_files
                                or not (member.isdir() or member.isfile())
                                or member.mode & 0o7000
                                or member.uid != 0
                                or member.gid != 0
                                or member.sparse is not None
                            ):
                                raise UpdateError("unsafe_artifact")
                            members.add(name)
                            target = tree / name
                            if member.isdir():
                                target.mkdir(parents=True, mode=0o700, exist_ok=True)
                                continue
                            total += member.size
                            if total > artifact.max_expanded_bytes or member.size < 0:
                                raise UpdateError("quota_exceeded")
                            target.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
                            with (
                                archive.extractfile(member) as incoming,
                                target.open("xb") as outgoing,
                            ):
                                shutil.copyfileobj(incoming, outgoing, length=64 * 1024)
                                outgoing.flush()
                                os.fsync(outgoing.fileno())
                            target.chmod(0o555 if member.mode & 0o111 else 0o444)
            except (tarfile.TarError, OSError, EOFError):
                raise UpdateError("unsafe_artifact", "Archive staging failed") from None
            self.verify(tree, artifact, staged=True)
            for path in tree.rglob("*"):
                if path.is_dir():
                    path.chmod(0o555)
            os.replace(tree, destination)
            destination.chmod(0o555)
            parent = os.open(self.root, os.O_DIRECTORY)
            try:
                os.fsync(parent)
            finally:
                os.close(parent)
        return destination

    def verify(self, directory: Path, artifact, staged=False):
        directory = Path(directory)
        if (
            directory.is_symlink()
            or not directory.is_dir()
            or (not staged and directory.stat().st_mode & 0o222)
            or directory.parent.resolve() != self.root.resolve()
            and not staged
        ):
            raise UpdateError("unsafe_artifact")
        index_path = directory / "content-index.json"
        if (
            index_path.is_symlink()
            or not index_path.is_file()
            or index_path.stat().st_size > 1024 * 1024
            or index_path.stat().st_mode & 0o222
            or index_path.stat().st_uid != os.geteuid()
        ):
            raise UpdateError("unsafe_artifact")
        raw = index_path.read_bytes()
        if digest(raw) != artifact.content_index_digest:
            raise UpdateError("untrusted_release")
        index = loads(raw)
        if (
            set(index) != {"content_index_version", "platform", "python", "files"}
            or type(index["content_index_version"]) is not int
            or index["content_index_version"] != 1
            or index["platform"] != artifact.platform
            or index["python"] != "3.12"
            or not isinstance(index["files"], list)
            or len(index["files"]) > self.max_files
        ):
            raise UpdateError("unsupported_platform")
        expected = {"content-index.json"}
        expanded = len(raw)
        for entry in index["files"]:
            if (
                set(entry) != {"path", "digest", "size", "executable"}
                or type(entry["size"]) is not int
                or entry["size"] < 0
                or type(entry["executable"]) is not bool
            ):
                raise UpdateError("unsafe_artifact")
            name = relative(entry["path"])
            if name in expected:
                raise UpdateError("unsafe_artifact")
            expected.add(name)
            target = directory / name
            if (
                target.is_symlink()
                or not target.is_file()
                or target.stat().st_uid != os.geteuid()
                or target.stat().st_mode & 0o222
                or target.stat().st_size != entry["size"]
                or bool(target.stat().st_mode & 0o111) != entry["executable"]
            ):
                raise UpdateError("unsafe_artifact")
            hasher = hashlib.sha256()
            with target.open("rb") as stream:
                for chunk in iter(lambda: stream.read(64 * 1024), b""):
                    hasher.update(chunk)
            if "sha256:" + hasher.hexdigest() != entry["digest"]:
                raise UpdateError("untrusted_release")
            expanded += entry["size"]
        actual = set()
        for path in directory.rglob("*"):
            if (
                path.is_symlink()
                or not (path.is_dir() or path.is_file())
                or path.stat().st_uid != os.geteuid()
                or (not staged and path.is_dir() and path.stat().st_mode & 0o222)
            ):
                raise UpdateError("unsafe_artifact")
            if path.is_file():
                actual.add(str(path.relative_to(directory)))
        if actual != expected or expanded > min(artifact.max_expanded_bytes, self.max_expanded):
            raise UpdateError("unsafe_artifact")

    def activate(self, artifact, pointer: Path):
        directory = self.root / artifact.digest.removeprefix("sha256:")
        self.verify(directory, artifact)
        pointer = Path(pointer)
        if (
            pointer.parent.is_symlink()
            or pointer.parent.stat().st_uid != os.geteuid()
            or pointer.parent.stat().st_mode & 0o022
        ):
            raise UpdateError("unsafe_storage")
        if pointer.exists() and not pointer.is_symlink():
            raise UpdateError("unsafe_storage")
        temporary = pointer.with_name(pointer.name + ".candidate")
        if temporary.exists() or temporary.is_symlink():
            raise UpdateError("outcome_unknown", "Interrupted pointer handoff requires inspection")
        os.symlink(directory, temporary)
        os.replace(temporary, pointer)
        descriptor = os.open(pointer.parent, os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return directory
