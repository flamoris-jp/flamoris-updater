"""Application-owned file identity and bounded read-only inventory."""

import hashlib
import os
import stat
from pathlib import Path

from pydantic import Field

from .errors import UpdateError
from .models import ID, Model
from .wire import digest, dumps


class TreeBinding(Model):
    id: ID
    path: str
    max_bytes: int = Field(gt=0, le=2**50)
    # This format uses the Core's bounded 4096-member JSON contract.
    max_files: int = Field(gt=0, le=4096)


def protected_read(path: Path, *, private=False, limit=1024 * 1024):
    path = Path(path)
    if not path.is_absolute():
        raise UpdateError("invalid_profile")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid not in {0, os.geteuid()}
            or info.st_mode & (0o077 if private else 0o022)
            or info.st_size > limit
        ):
            raise UpdateError("unsafe_storage")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            raw = stream.read(limit + 1)
        after = os.fstat(fd)
        if len(raw) > limit or (after.st_size, after.st_mtime_ns, after.st_ctime_ns) != (
            info.st_size,
            info.st_mtime_ns,
            info.st_ctime_ns,
        ):
            raise UpdateError("resource_changed")
        return raw
    finally:
        os.close(fd)


def _regular(info):
    # A setgid directory is a normal shared-storage contract: newly-created
    # members inherit the directory group.  Keep rejecting every executable
    # privilege bit on files, setuid everywhere, and sticky directories.  The
    # latter are intentionally outside the v1 application-resource profile.
    privileged_mode = info.st_mode & (stat.S_ISUID | stat.S_ISVTX)
    if stat.S_ISREG(info.st_mode):
        privileged_mode |= info.st_mode & stat.S_ISGID
    if (
        not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode))
        or (stat.S_ISREG(info.st_mode) and info.st_nlink != 1)
        or privileged_mode
    ):
        raise UpdateError("unsafe_storage", "Special files, links and privileged modes are refused")


class TreeResource:
    def __init__(self, binding: TreeBinding):
        self.binding = binding
        self.root = Path(binding.path)
        if not self.root.is_absolute() or self.root.resolve() != self.root:
            raise UpdateError("invalid_profile")

    def binding_digest(self):
        info = self.root.stat(follow_symlinks=False)
        _regular(info)
        if not stat.S_ISDIR(info.st_mode):
            raise UpdateError("invalid_profile")
        return digest(
            dumps(
                {
                    "path": str(self.root),
                    "device": info.st_dev,
                    "inode": info.st_ino,
                    "uid": info.st_uid,
                    "gid": info.st_gid,
                    "mode": stat.S_IMODE(info.st_mode),
                }
            )
        )

    @staticmethod
    def _open(root, relative, flags):
        """Pin each ancestor; an ancestor symlink cannot redirect a file read."""
        fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            parts = Path(relative).parts
            if not parts:
                return os.dup(fd)
            for part in parts[:-1]:
                following = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = following
            return os.open(parts[-1], flags | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        finally:
            os.close(fd)

    def _paths(self, root):
        pending, paths = [Path(".")], []
        while pending:
            relative = pending.pop()
            paths.append(relative)
            fd = self._open(root, relative, os.O_RDONLY)
            try:
                info = os.fstat(fd)
                _regular(info)
                if stat.S_ISDIR(info.st_mode):
                    with os.scandir(fd) as entries:
                        for entry in entries:
                            if len(paths) + len(pending) >= self.binding.max_files:
                                raise UpdateError("quota_exceeded")
                            pending.append(relative / entry.name)
            finally:
                os.close(fd)
        return sorted(paths, key=lambda path: path.as_posix())

    def inventory(self, root=None) -> list[dict]:
        root = self.root if root is None else Path(root)
        result, total = [], 0
        for relative in self._paths(root):
            path = root / relative
            if len(result) >= self.binding.max_files:
                raise UpdateError("quota_exceeded")
            before = path.stat(follow_symlinks=False)
            _regular(before)
            item = {
                "path": path.relative_to(root).as_posix(),
                "mode": stat.S_IMODE(before.st_mode),
                "uid": before.st_uid,
                "gid": before.st_gid,
                "kind": "directory",
            }
            if stat.S_ISREG(before.st_mode):
                total += before.st_size
                if total > self.binding.max_bytes:
                    raise UpdateError("quota_exceeded")
                fd = self._open(root, relative, os.O_RDONLY)
                try:
                    pinned = os.fstat(fd)
                    if (pinned.st_dev, pinned.st_ino) != (before.st_dev, before.st_ino):
                        raise UpdateError("resource_changed")
                    hasher = hashlib.sha256()
                    with os.fdopen(fd, "rb", closefd=False) as stream:
                        while chunk := stream.read(1024 * 1024):
                            hasher.update(chunk)
                    after = os.fstat(fd)
                    if (after.st_size, after.st_mtime_ns, after.st_ctime_ns) != (
                        before.st_size,
                        before.st_mtime_ns,
                        before.st_ctime_ns,
                    ):
                        raise UpdateError("resource_changed")
                finally:
                    os.close(fd)
                item.update(kind="file", size=before.st_size, digest="sha256:" + hasher.hexdigest())
            result.append(item)
        return result
