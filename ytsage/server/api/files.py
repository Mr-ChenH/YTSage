from __future__ import annotations

from typing import Annotated, Callable

from fastapi import APIRouter, Depends, Header, Query, Request, Response

from ..config import ServerConfig
from ..files.catalog import delete_download_file, delete_download_folder, list_files, resolve_download_file, resolve_download_folder
from ..files.exports import folder_download_response, folder_manifest_response
from ..files.responses import ranged_download_response, stream_response

AuthDependency = Callable[..., None]


def create_files_router(config: ServerConfig, auth_dependency: AuthDependency) -> APIRouter:
    router = APIRouter(prefix="/api", dependencies=[Depends(auth_dependency)])

    @router.get("/files")
    def files(request: Request, q: str | None = None, folder: str | None = None, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200), media_only: bool = Query(False), direct_only: bool = Query(False)):
        return list_files(config.download_dir, request, query=q, folder=folder, offset=offset, limit=limit, media_only=media_only, direct_only=direct_only)

    @router.delete("/folders", status_code=204)
    def delete_folder(folder: str) -> Response:
        delete_download_folder(config.download_dir, folder)
        return Response(status_code=204)

    @router.get("/folders/download", name="download_folder")
    def download_folder(folder: str | None = None):
        folder_path, archive_name = resolve_download_folder(config.download_dir, folder)
        return folder_download_response(folder_path, archive_name)

    @router.get("/folders/manifest", name="folder_manifest")
    def folder_manifest(request: Request, folder: str | None = None, format: str = "aria2"):
        folder_path, archive_name = resolve_download_folder(config.download_dir, folder)
        return folder_manifest_response(config.download_dir, folder_path, archive_name, request, format)

    @router.delete("/files/{file_id}", status_code=204)
    def delete_file(file_id: str) -> Response:
        delete_download_file(config.download_dir, file_id)
        return Response(status_code=204)

    @router.get("/files/{file_id}/download", name="download_file")
    def download_file(file_id: str, range_header: Annotated[str | None, Header(alias="Range")] = None):
        return ranged_download_response(resolve_download_file(config.download_dir, file_id), range_header)

    @router.get("/files/{file_id}/stream", name="stream_file")
    def stream_file(file_id: str, range_header: Annotated[str | None, Header(alias="Range")] = None):
        return stream_response(resolve_download_file(config.download_dir, file_id), range_header)

    return router
