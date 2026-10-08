import gzip
import hashlib
import re
import shutil
import tarfile
import tempfile
from pathlib import Path

from flamoris_update_core.errors import UpdateError
from flamoris_update_core.wire import digest, loads

from .artifacts import BoundedReader, origin
from .process import bounded_command

ACCEPT = "application/vnd.oci.image.index.v1+json, application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json, application/vnd.docker.distribution.manifest.list.v2+json"


class HashReader(BoundedReader):
    def __init__(self, source, budget):
        super().__init__(source, budget)
        self.hasher = hashlib.sha256()

    def read(self, size=-1):
        result = super().read(size)
        self.hasher.update(result)
        return result


class OCIStore:
    def __init__(self, fetcher, binding, quota, authorization=None):
        self.fetcher, self.binding, self.quota = fetcher, binding, quota
        self.headers = {"Accept": ACCEPT}
        if authorization:
            self.headers["Authorization"] = authorization

    def descriptor(self, obj):
        if (
            not isinstance(obj, dict)
            or not isinstance(obj.get("digest"), str)
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", obj["digest"])
            or type(obj.get("size")) is not int
            or obj["size"] < 0
            or not isinstance(obj.get("mediaType"), str)
        ):
            raise UpdateError("unsafe_artifact")
        return obj

    def _fetch(self, kind, identity, limit, expected_size=None):
        url = (
            self.binding.registry_origin.rstrip("/")
            + "/v2/"
            + self.binding.repository
            + "/"
            + kind
            + "/"
            + identity
        )
        raw = self.fetcher.bytes(url, limit, self.headers)
        if digest(raw) != identity or expected_size is not None and len(raw) != expected_size:
            raise UpdateError("untrusted_release")
        return raw

    def resolve(self, artifact):
        if (
            artifact.kind != "docker"
            or artifact.locator
            != self.binding.registry_origin.removeprefix("https://").rstrip("/")
            + "/"
            + self.binding.repository
            + "@"
            + artifact.digest
            or artifact.max_expanded_bytes > self.quota.max_expanded_bytes
        ):
            raise UpdateError("untrusted_origin")
        raw = self._fetch("manifests", artifact.digest, 1024 * 1024)
        manifest = loads(raw)
        selected = artifact.digest
        os_name, arch = artifact.platform.split("/")
        if "manifests" in manifest:
            candidates = [
                self.descriptor(x)
                for x in manifest["manifests"]
                if x.get("platform", {}).get("os") == os_name
                and x.get("platform", {}).get("architecture") == arch
                and x.get("platform", {}).get("variant")
                in {None, "v8" if arch == "arm64" else None}
            ]
            if len(candidates) != 1:
                raise UpdateError("unsupported_platform")
            selected = candidates[0]["digest"]
            manifest = loads(self._fetch("manifests", selected, 1024 * 1024, candidates[0]["size"]))
        if (
            type(manifest.get("schemaVersion")) is not int
            or manifest["schemaVersion"] != 2
            or not isinstance(manifest.get("layers"), list)
            or len(manifest["layers"]) > 256
        ):
            raise UpdateError("unsafe_artifact")
        config_desc = self.descriptor(manifest.get("config"))
        if config_desc["digest"] != artifact.content_index_digest:
            raise UpdateError("untrusted_release", "OCI filesystem configuration index differs")
        config = loads(
            self._fetch("blobs", config_desc["digest"], 1024 * 1024, config_desc["size"])
        )
        if (
            config.get("os") != os_name
            or config.get("architecture") != arch
            or config.get("rootfs", {}).get("type") != "layers"
        ):
            raise UpdateError("unsupported_platform")
        layers = [self.descriptor(x) for x in manifest["layers"]]
        diff_ids = config["rootfs"].get("diff_ids")
        if (
            not isinstance(diff_ids, list)
            or len(diff_ids) != len(layers)
            or sum(x["size"] for x in layers) > self.quota.max_download_bytes
        ):
            raise UpdateError("quota_exceeded")
        data_directory = Path(self.binding.daemon_data_directory)
        if (
            data_directory.is_symlink()
            or not data_directory.is_dir()
            or shutil.disk_usage(data_directory).free
            < self.quota.reserve_bytes + self.quota.max_download_bytes + artifact.max_expanded_bytes
        ):
            raise UpdateError("quota_exceeded")
        used, files = 0, 0
        for descriptor, expected_diff in zip(layers, diff_ids, strict=True):
            media = descriptor["mediaType"]
            if media not in {
                "application/vnd.oci.image.layer.v1.tar+gzip",
                "application/vnd.oci.image.layer.v1.tar",
                "application/vnd.docker.image.rootfs.diff.tar.gzip",
            }:
                raise UpdateError(
                    "unsupported_platform", "Only distributable gzip/raw OCI layers are supported"
                )
            with tempfile.TemporaryFile(dir=data_directory) as spool:
                checksum = hashlib.sha256()
                size = 0
                url = (
                    self.binding.registry_origin.rstrip("/")
                    + "/v2/"
                    + self.binding.repository
                    + "/blobs/"
                    + descriptor["digest"]
                )
                for chunk in self.fetcher.chunks(
                    url, min(descriptor["size"], self.quota.max_download_bytes), self.headers
                ):
                    spool.write(chunk)
                    checksum.update(chunk)
                    size += len(chunk)
                if (
                    size != descriptor["size"]
                    or "sha256:" + checksum.hexdigest() != descriptor["digest"]
                ):
                    raise UpdateError("untrusted_release")
                spool.seek(0)
                source = gzip.GzipFile(fileobj=spool) if media.endswith("gzip") else spool
                reader = HashReader(source, artifact.max_expanded_bytes - used)
                logical = 0
                try:
                    with tarfile.open(fileobj=reader, mode="r|") as archive:
                        for member in archive:
                            files += 1
                            logical += member.size
                            if (
                                member.sparse is not None
                                or member.size < 0
                                or files > self.quota.max_files
                                or used + logical > artifact.max_expanded_bytes
                            ):
                                raise UpdateError("quota_exceeded")
                    while reader.read(64 * 1024):
                        pass
                except (tarfile.TarError, OSError, EOFError):
                    raise UpdateError("unsafe_artifact") from None
                if "sha256:" + reader.hasher.hexdigest() != expected_diff:
                    raise UpdateError("untrusted_release")
                used = artifact.max_expanded_bytes - reader.remaining
        return {
            "artifact_digest": artifact.digest,
            "selected_digest": selected,
            "config_digest": config_desc["digest"],
            "diff_ids": diff_ids,
            "platform": artifact.platform,
            "expanded_bytes": used,
        }


class DockerDriver:
    def __init__(self, store, binding, journal, command=bounded_command):
        self.store, self.binding, self.journal, self.command = store, binding, journal, command
        self._validate_binding()

    def _validate_binding(self):
        import os

        b = self.binding
        origin(b.registry_origin)
        socket = Path(b.daemon_socket)
        if (
            not socket.is_absolute()
            or socket.is_symlink()
            or not socket.is_socket()
            or socket.stat().st_uid != 0
        ):
            raise UpdateError(
                "invalid_profile", "Docker requires the protected local daemon socket"
            )
        if (
            not re.fullmatch(r"[a-z0-9]+(?:[._/-][a-z0-9]+)*", b.repository)
            or not re.fullmatch(r"[1-9][0-9]*:[0-9]+", b.runtime_user)
            or len(b.container_name) > 64
            or b.network == "host"
        ):
            raise UpdateError("invalid_profile")
        directory = Path(b.docker_config_directory)
        if (
            directory.is_symlink()
            or not directory.is_dir()
            or directory.stat().st_uid != os.geteuid()
            or directory.stat().st_mode & 0o077
        ):
            raise UpdateError("unsafe_storage")
        for mount in b.mounts:
            source, target = Path(mount.source), Path(mount.target)
            protected = [
                Path(x)
                for x in [
                    "/etc",
                    "/usr",
                    "/bin",
                    "/sbin",
                    "/lib",
                    "/lib64",
                    "/boot",
                    "/root",
                    "/proc",
                    "/sys",
                    "/dev",
                    "/run",
                    "/var/run",
                    b.daemon_socket,
                    b.daemon_data_directory,
                    b.docker_config_directory,
                ]
            ]
            if (
                any(source.is_relative_to(x) or x.is_relative_to(source) for x in protected)
                or not source.is_absolute()
                or not target.is_absolute()
                or "," in mount.source + mount.target
                or any(c in mount.source + mount.target for c in "\n\r\x00")
                or source.is_symlink()
                or not source.exists()
                or str(source).startswith(("/proc/", "/sys/", "/dev/", "/run/", "/var/run/"))
                or source == Path("/")
                or str(target) in {"/", "/proc", "/sys", "/dev"}
            ):
                raise UpdateError(
                    "invalid_profile", "Docker mounts are outside the allowed local binding"
                )

    def _docker(self, *args, timeout=120):
        return self.command(
            [
                "/usr/bin/docker",
                "--host",
                "unix://" + self.binding.daemon_socket,
                "--config",
                self.binding.docker_config_directory,
                *args,
            ],
            timeout=timeout,
        )

    def _image(self, prepared):
        locator = (
            self.binding.registry_origin.removeprefix("https://").rstrip("/")
            + "/"
            + self.binding.repository
            + "@"
            + prepared["selected_digest"]
        )
        obj = loads(b'{"images":' + self._docker("image", "inspect", locator) + b"}")
        images = obj["images"]
        if (
            len(images) != 1
            or images[0].get("Id") != prepared["config_digest"]
            or images[0].get("Os") + "/" + images[0].get("Architecture") != prepared["platform"]
            or locator not in images[0].get("RepoDigests", [])
            or images[0].get("RootFS", {}).get("Layers") != prepared["diff_ids"]
            or images[0].get("Config", {}).get("Volumes")
        ):
            raise UpdateError("untrusted_release")
        return locator

    def preparation_id(self, manifest):
        from flamoris_update_core.wire import dumps

        return digest(
            dumps(
                {
                    "deployment": self.binding.deployment_id,
                    "artifact": manifest.artifact.model_dump(),
                }
            )
        )

    def prepare(self, manifest):
        self._validate_binding()
        prepared = self.store.resolve(manifest.artifact)
        locator = (
            self.binding.registry_origin.removeprefix("https://").rstrip("/")
            + "/"
            + self.binding.repository
            + "@"
            + prepared["selected_digest"]
        )
        self._docker(
            "image", "pull", "--platform", manifest.artifact.platform, locator, timeout=600
        )
        self._image(prepared)
        with self.journal.transaction() as db:
            self.journal.put("docker_prepared", self.preparation_id(manifest), prepared, db)

    def _exists(self):
        names = (
            self._docker(
                "container",
                "ls",
                "--all",
                "--format",
                "{{.Names}}",
                "--filter",
                "name=^/" + re.escape(self.binding.container_name) + "$",
            )
            .decode()
            .splitlines()
        )
        if any(x != self.binding.container_name for x in names) or len(names) > 1:
            raise UpdateError("outcome_unknown")
        return bool(names)

    def stop(self):
        if self._exists():
            self._docker("container", "stop", "--timeout", "30", self.binding.container_name)
            obj = loads(
                b'{"containers":'
                + self._docker("container", "inspect", self.binding.container_name)
                + b"}"
            )
            if obj["containers"][0]["State"]["Running"]:
                raise UpdateError("outcome_unknown")

    def activate(self, manifest, operation_id):
        self._validate_binding()
        prepared = self.journal.get("docker_prepared", self.preparation_id(manifest))
        if prepared is None:
            raise UpdateError("untrusted_release")
        locator = self._image(prepared)
        token = digest(operation_id.encode()).removeprefix("sha256:")[:12]
        candidate = self.binding.container_name + "-candidate-" + token
        previous = self.binding.container_name + "-previous-" + token
        argv = [
            "container",
            "create",
            "--name",
            candidate,
            "--user",
            self.binding.runtime_user,
            "--read-only",
            "--no-healthcheck",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--pids-limit",
            str(self.binding.pids_limit),
            "--memory",
            str(self.binding.memory_bytes),
            "--network",
            self.binding.network,
            "--label",
            "flamoris.updater.operation=" + operation_id,
        ]
        for mount in self.binding.mounts:
            argv.extend(
                [
                    "--mount",
                    "type=bind,src="
                    + mount.source
                    + ",dst="
                    + mount.target
                    + (",readonly" if mount.read_only else ""),
                ]
            )
        if self.binding.environment_file:
            from .config import protected_read

            protected_read(self.binding.environment_file, private=True)
            argv.extend(["--env-file", self.binding.environment_file])
        self._docker(*argv, locator)
        if self._exists():
            obj = loads(
                b'{"containers":'
                + self._docker("container", "inspect", self.binding.container_name)
                + b"}"
            )
            if obj["containers"][0]["State"]["Running"]:
                raise UpdateError("outcome_unknown")
            self._docker("container", "rename", self.binding.container_name, previous)
        self._docker("container", "rename", candidate, self.binding.container_name)
        self._docker("container", "start", self.binding.container_name)
