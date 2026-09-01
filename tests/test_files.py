from pathlib import Path

from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from ytsage.server.services.files import (
    delete_download_file,
    delete_download_folder,
    encode_file_id,
    list_files,
)


def test_list_files_filters_direct_playable_media_before_pagination(tmp_path: Path) -> None:
    root = tmp_path / "downloads"
    folder = root / "course"
    nested = folder / "nested"
    nested.mkdir(parents=True)
    (folder / "lesson.mp4").write_bytes(b"video")
    (folder / "notes.txt").write_text("notes", encoding="utf-8")
    (nested / "extra.mp3").write_bytes(b"audio")
    request = Mock()
    request.url_for.side_effect = lambda name, file_id: f"http://test/{name}/{file_id}"

    result = list_files(root, request, folder="course", limit=1, media_only=True, direct_only=True)

    assert result.total == 1
    assert [file.name for file in result.files] == ["lesson.mp4"]
    assert result.folders == ["course", "course/nested"]


def test_delete_download_file_and_empty_parent(tmp_path: Path) -> None:
    root = tmp_path / "downloads"
    folder = root / "course"
    folder.mkdir(parents=True)
    target = folder / "video.mp4"
    target.write_bytes(b"video")

    delete_download_file(root, encode_file_id("course/video.mp4"))

    assert not target.exists()
    assert not folder.exists()
    assert root.exists()


def test_delete_download_folder_recursively(tmp_path: Path) -> None:
    root = tmp_path / "downloads"
    nested = root / "course" / "section"
    nested.mkdir(parents=True)
    (nested / "video.mp4").write_bytes(b"video")

    delete_download_folder(root, "course")

    assert not (root / "course").exists()
    assert root.exists()


@pytest.mark.parametrize("folder", ["", ".", "/"])
def test_delete_download_folder_rejects_root(tmp_path: Path, folder: str) -> None:
    root = tmp_path / "downloads"
    root.mkdir()

    with pytest.raises(HTTPException) as exc_info:
        delete_download_folder(root, folder)

    assert exc_info.value.status_code == 400
    assert root.exists()


def test_delete_download_folder_rejects_path_traversal(tmp_path: Path) -> None:
    root = tmp_path / "downloads"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep", encoding="utf-8")

    with pytest.raises(HTTPException) as exc_info:
        delete_download_folder(root, "../outside")

    assert exc_info.value.status_code == 400
    assert (outside / "keep.txt").exists()
