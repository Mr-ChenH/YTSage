from __future__ import annotations

from typing import Callable

from fastapi import APIRouter, Depends

from ..config import ServerConfig
from ..models import AnalyzeRequest, AnalyzeResponse
from ..services import analyzer
from ..services.accounts import AccountService
from ..services.douyin_proofs import DouyinDownloadProofStore

AuthDependency = Callable[..., None]


def create_analysis_router(
    config: ServerConfig,
    account_service: AccountService,
    auth_dependency: AuthDependency,
    douyin_proofs: DouyinDownloadProofStore | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api", dependencies=[Depends(auth_dependency)])

    @router.post("/analyze", response_model=AnalyzeResponse)
    def analyze_url(request: AnalyzeRequest) -> AnalyzeResponse:
        return analyzer.analyze(
            request,
            config_dir=config.config_dir,
            account_service=account_service,
            douyin_proofs=douyin_proofs,
        )

    return router
