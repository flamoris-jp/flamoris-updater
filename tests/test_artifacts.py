import gzip
import io
import tarfile
from types import SimpleNamespace

import httpx
import pytest

from flamoris_update_core.errors import UpdateError
from flamoris_update_core.models import Artifact
from flamoris_update_core.wire import digest, dumps
from flamoris_updater_adapters.artifacts import BoundedReader, Fetcher, NativeStore
from flamoris_updater_adapters.docker import OCIStore
from flamoris_updater_adapters.process import bounded_command


def archive(files, link=None, uid=0):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w:gz") as tar:
        for name, raw in files.items():
            member = tarfile.TarInfo(name)
            member.size = len(raw)
            member.mode = 0o444
            member.uid = uid
            tar.addfile(member, io.BytesIO(raw))
        if link:
            member = tarfile.TarInfo(link)
            member.type = tarfile.SYMTYPE
            member.linkname = "/etc/passwd"
            tar.addfile(member)
    return stream.getvalue()


def native(tmp_path, extra=None, link=None, uid=0):
    body = b"immutable artifact"
    index = dumps(
        {
            "content_index_version": 1,
            "platform": "linux/amd64",
            "python": "3.12",
            "files": [
                {
                    "path": "application.txt",
                    "digest": digest(body),
                    "size": len(body),
                    "executable": False,
                }
            ],
        }
    )
    raw = archive(
        {"application.txt": body, "content-index.json": index, **(extra or {})}, link, uid
    )
    client = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=raw))
    )
    fetch = Fetcher(["https://release.example.invalid"], client)
    store = NativeStore(
        tmp_path / "staged",
        fetch,
        max_download=1024 * 1024,
        max_expanded=1024 * 1024,
        max_files=100,
        reserve=1024,
    )
    artifact = Artifact(
        kind="native",
        platform="linux/amd64",
        locator="https://release.example.invalid/app.tar.gz",
        digest=digest(raw),
        max_expanded_bytes=1024 * 1024,
        content_index_digest=digest(index),
    )
    return store, artifact


def test_native_staging_seals_files_and_atomic_pointer(tmp_path):
    store, a = native(tmp_path)
    path = store.prepare(a)
    assert path.stat().st_mode & 0o222 == 0
    assert store.prepare(a) == path
    root = tmp_path / "active"
    root.mkdir()
    pointer = root / "current"
    store.activate(a, pointer)
    assert pointer.resolve() == path.resolve()
    (path / "application.txt").chmod(0o644)
    with pytest.raises(UpdateError):
        store.activate(a, pointer)


@pytest.mark.parametrize(
    "extra,link,uid",
    [
        ({"../escape": b"x"}, None, 0),
        ({"unindexed": b"x"}, None, 0),
        (None, "link", 0),
        (None, None, 1000),
        ({"/absolute": b"x"}, None, 0),
    ],
)
def test_native_rejects_unconfined_unindexed_links_ownership(tmp_path, extra, link, uid):
    store, a = native(tmp_path, extra, link, uid)
    with pytest.raises(UpdateError):
        store.prepare(a)
    assert not (tmp_path / "escape").exists()
    assert not (store.root / a.digest.removeprefix("sha256:")).exists()


def test_reader_allows_eof_at_exact_budget_and_rejects_extra_byte():
    r = BoundedReader(io.BytesIO(b"abc"), 3)
    assert r.read(65536) == b"abc" and r.read(65536) == b""
    with pytest.raises(UpdateError):
        BoundedReader(io.BytesIO(b"abcd"), 3).read(65536)


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example.invalid/app",
        "https://release.example.invalid/%2e%2e/app",
        "http://release.example.invalid/app",
        "https://user:password@release.example.invalid/app",
    ],
)
def test_fetcher_rejects_unapproved_destinations_before_network(url):
    count = []
    f = Fetcher(
        ["https://release.example.invalid"],
        httpx.Client(transport=httpx.MockTransport(lambda r: count.append(r))),
    )
    with pytest.raises(UpdateError):
        f.bytes(url, 10)
    assert count == []


def test_fetcher_rejects_redirect_and_stream_quota():
    for status, headers, body in [
        (302, {"location": "https://evil.example.invalid"}, b""),
        (200, {}, b"too large"),
    ]:
        f = Fetcher(
            ["https://release.example.invalid"],
            httpx.Client(
                transport=httpx.MockTransport(
                    lambda r: httpx.Response(status, headers=headers, content=body)
                )
            ),
        )
        with pytest.raises(UpdateError):
            f.bytes("https://release.example.invalid/a", 3)


def test_command_output_is_bounded_and_private_diagnostics_masked():
    with pytest.raises(UpdateError) as rejected:
        bounded_command(
            ["/usr/bin/python3", "-c", "import sys; sys.stdout.write('private-output'*1000000)"],
            limit=4096,
        )
    assert "private-output" not in str(rejected.value)
    with pytest.raises(UpdateError):
        bounded_command(["/usr/bin/python3", "-c", "import time; time.sleep(10)"], timeout=1)


def oci(tmp_path, corrupt=False):
    rawtar = io.BytesIO()
    with tarfile.open(fileobj=rawtar, mode="w") as archive:
        member = tarfile.TarInfo("file")
        member.size = 3
        archive.addfile(member, io.BytesIO(b"abc"))
    layer = gzip.compress(rawtar.getvalue())
    config = dumps(
        {
            "os": "linux",
            "architecture": "amd64",
            "rootfs": {"type": "layers", "diff_ids": [digest(rawtar.getvalue())]},
        }
    )

    def descriptor(raw, media):
        return {"mediaType": media, "digest": digest(raw), "size": len(raw)}

    image = dumps(
        {
            "schemaVersion": 2,
            "mediaType": "application/vnd.oci.image.manifest.v1+json",
            "config": descriptor(config, "application/vnd.oci.image.config.v1+json"),
            "layers": [descriptor(layer, "application/vnd.oci.image.layer.v1.tar+gzip")],
        }
    )
    selected = descriptor(image, "application/vnd.oci.image.manifest.v1+json")
    selected["platform"] = {"os": "linux", "architecture": "amd64"}
    index = dumps(
        {
            "schemaVersion": 2,
            "mediaType": "application/vnd.oci.image.index.v1+json",
            "manifests": [selected],
        }
    )
    objects = {digest(x): x for x in [index, image, config, layer]}
    if corrupt:
        objects[digest(layer)] = b"corrupt"
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, content=objects[request.url.path.rsplit("/", 1)[1]])
    )
    binding = SimpleNamespace(
        registry_origin="https://registry.example.invalid",
        repository="example/app",
        daemon_data_directory=str(tmp_path),
    )
    quota = SimpleNamespace(
        max_download_bytes=1024 * 1024,
        max_expanded_bytes=1024 * 1024,
        max_files=100,
        reserve_bytes=1024,
    )
    a = Artifact(
        kind="docker",
        platform="linux/amd64",
        locator="registry.example.invalid/example/app@" + digest(index),
        digest=digest(index),
        max_expanded_bytes=1024 * 1024,
        content_index_digest=digest(config),
    )
    return (
        OCIStore(
            Fetcher([binding.registry_origin], httpx.Client(transport=transport)), binding, quota
        ),
        a,
        image,
        config,
        rawtar.getvalue(),
    )


def test_oci_index_child_config_and_decompressed_layer_are_bound(tmp_path):
    store, a, image, config, rawtar = oci(tmp_path)
    resolved = store.resolve(a)
    assert resolved["selected_digest"] == digest(image) and resolved["config_digest"] == digest(
        config
    )
    assert resolved["diff_ids"] == [digest(rawtar)] and resolved["expanded_bytes"] == len(rawtar)
    with pytest.raises(UpdateError):
        store.resolve(a.model_copy(update={"platform": "linux/arm64"}))


def test_oci_rejects_corrupt_layers(tmp_path):
    store, a, _, _, _ = oci(tmp_path, True)
    with pytest.raises(UpdateError):
        store.resolve(a)
