"""Storage path ownership (VF-MVP-CORE-005).

`storage_path` is client-writable (POST /receipts, PATCH /receipts/{id}), so the service only
reads or deletes a stored file after is_receipt_storage_path_owned_by confirms the path lies
inside the requesting user's own storage area.
"""
from pathlib import Path
from uuid import uuid4

import pytest

from app.modules.receipts import receipt_storage_service
from app.modules.receipts.receipt_storage_service import is_receipt_storage_path_owned_by


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(receipt_storage_service.settings, "receipt_upload_dir", str(tmp_path / "uploads"))
    monkeypatch.setattr(receipt_storage_service.settings, "receipt_storage_bucket", "receipts")
    return tmp_path / "uploads"


def test_a_local_file_inside_the_users_directory_is_owned(root: Path) -> None:
    user = uuid4()

    assert is_receipt_storage_path_owned_by((root / str(user) / "a.jpg").as_posix(), user)
    assert is_receipt_storage_path_owned_by((root / str(user) / "nested" / "a.jpg").as_posix(), user)


def test_a_relative_stored_path_resolves_like_the_one_the_upload_produces(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = uuid4()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(receipt_storage_service.settings, "receipt_upload_dir", "uploads/receipts")

    assert is_receipt_storage_path_owned_by(f"uploads/receipts/{user}/a.jpg", user)
    assert not is_receipt_storage_path_owned_by(f"uploads/receipts/{uuid4()}/a.jpg", user)


@pytest.mark.parametrize(
    "build",
    [
        lambda root, user, other: root / str(other) / "a.jpg",  # another user's directory
        lambda root, user, other: root / "a.jpg",  # the shared root
        lambda root, user, other: root / str(user),  # the directory itself
        lambda root, user, other: root / str(user) / ".." / str(other) / "a.jpg",  # traversal
        lambda root, user, other: root / str(user) / ".." / ".." / "outside.jpg",
        lambda root, user, other: root.parent / "outside.jpg",
        lambda root, user, other: Path("/etc/passwd"),
        lambda root, user, other: Path(str(root / str(user)) + "-sibling") / "a.jpg",  # prefix lookalike
    ],
)
def test_local_paths_outside_the_users_directory_are_not_owned(root: Path, build) -> None:
    user, other = uuid4(), uuid4()

    assert not is_receipt_storage_path_owned_by(build(root, user, other).as_posix(), user)


def test_a_symlink_inside_the_users_directory_that_points_outside_is_not_owned(root: Path, tmp_path: Path) -> None:
    user = uuid4()
    (root / str(user)).mkdir(parents=True)
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"x")
    link = root / str(user) / "link.png"
    link.symlink_to(outside)

    assert not is_receipt_storage_path_owned_by(link.as_posix(), user)


def test_supabase_paths_must_name_the_configured_bucket_and_the_users_own_prefix(root: Path) -> None:
    user, other = uuid4(), uuid4()

    assert is_receipt_storage_path_owned_by(f"supabase://receipts/{user}/a.jpg", user)
    assert not is_receipt_storage_path_owned_by(f"supabase://receipts/{other}/a.jpg", user)
    assert not is_receipt_storage_path_owned_by(f"supabase://other-bucket/{user}/a.jpg", user)
    assert not is_receipt_storage_path_owned_by(f"supabase://receipts/{user}", user)
    assert not is_receipt_storage_path_owned_by(f"supabase://receipts/{user}/", user)
    assert not is_receipt_storage_path_owned_by(f"supabase://receipts/{user}/../{other}/a.jpg", user)
    assert not is_receipt_storage_path_owned_by(f"supabase://receipts/{user}/./a.jpg", user)
    assert not is_receipt_storage_path_owned_by(f"supabase://receipts/{user}//a.jpg", user)
    assert not is_receipt_storage_path_owned_by("supabase://receipts", user)
    assert not is_receipt_storage_path_owned_by("supabase:///", user)
