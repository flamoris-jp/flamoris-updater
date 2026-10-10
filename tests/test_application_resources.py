import os

import pytest

from flamoris_update_core.errors import UpdateError
from flamoris_update_core.resources import TreeBinding, TreeResource, protected_read


def resource(tmp_path, max_files=20):
    root = tmp_path / "data"
    root.mkdir(mode=0o700)
    (root / "conversation.json").write_bytes(b'{"history":["keep"]}')
    (root / "conversation.json").chmod(0o600)
    return TreeResource(TreeBinding(id="data", path=str(root), max_bytes=4096, max_files=max_files))


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "fifo"])
def test_inventory_refuses_link_and_special_members(tmp_path, kind):
    owner = resource(tmp_path)
    member = owner.root / "unsafe"
    if kind == "symlink":
        member.symlink_to(owner.root / "conversation.json")
    elif kind == "hardlink":
        os.link(owner.root / "conversation.json", member)
    else:
        os.mkfifo(member)
    with pytest.raises((UpdateError, OSError)):
        owner.inventory()
    assert not (tmp_path / "backup").exists()


def test_file_budget_includes_directories_and_does_not_expand_unbounded_tree(tmp_path):
    owner = resource(tmp_path, max_files=2)
    (owner.root / "extra").mkdir()
    with pytest.raises(UpdateError) as failure:
        owner.inventory()
    assert failure.value.code == "quota_exceeded"


def test_binding_changes_when_storage_permissions_change(tmp_path):
    owner = resource(tmp_path)
    old = owner.binding_digest()
    owner.root.chmod(0o750)
    assert owner.binding_digest() != old


@pytest.mark.parametrize(
    ("kind", "mode"),
    [("file", 0o2600), ("file", 0o4600), ("directory", 0o1700), ("directory", 0o4700)],
)
def test_privileged_modes_remain_refused(tmp_path, kind, mode):
    owner = resource(tmp_path)
    member = owner.root / "privileged"
    if kind == "directory":
        member.mkdir()
    else:
        member.write_text("unsafe")
    member.chmod(mode)

    with pytest.raises(UpdateError) as failure:
        owner.inventory()

    assert failure.value.code == "unsafe_storage"


def test_protected_reader_refuses_credentials_readable_by_other_users(tmp_path):
    secret = tmp_path / "dsn"
    secret.write_text("never-return-this")
    secret.chmod(0o644)
    with pytest.raises(UpdateError):
        protected_read(secret, private=True)
