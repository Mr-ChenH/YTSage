"""Compatibility facade for download file services.

New code should import focused modules from ``ytsage.server.files``.
"""

from fastapi.responses import FileResponse

from ..files.catalog import (
    AUDIO_EXTENSIONS,
    PLAYABLE_EXTENSIONS,
    SUBTITLE_EXTENSIONS,
    VIDEO_EXTENSIONS,
    classify_file,
    decode_file_id,
    delete_download_file,
    delete_download_folder,
    encode_file_id,
    list_files,
    resolve_download_file,
    resolve_download_folder,
    safe_folder_filter,
)
from ..files.exports import (
    ZipStream,
    folder_download_response,
    folder_files,
    folder_manifest_response,
    folder_zip_iterator,
)
from ..files.responses import file_iterator, range_response, ranged_download_response, stream_response

_safe_folder_filter = safe_folder_filter
_ZipStream = ZipStream
_folder_files = folder_files
_folder_zip_iterator = folder_zip_iterator
_file_iterator = file_iterator
_range_response = range_response


def download_response(path):
    return FileResponse(path, filename=path.name)


__all__ = [
    "AUDIO_EXTENSIONS",
    "PLAYABLE_EXTENSIONS",
    "SUBTITLE_EXTENSIONS",
    "VIDEO_EXTENSIONS",
    "classify_file",
    "decode_file_id",
    "delete_download_file",
    "delete_download_folder",
    "download_response",
    "encode_file_id",
    "folder_download_response",
    "folder_manifest_response",
    "list_files",
    "ranged_download_response",
    "resolve_download_file",
    "resolve_download_folder",
    "stream_response",
]
