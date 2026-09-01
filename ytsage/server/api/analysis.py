from __future__ import annotations

from typing import Callable

from fastapi import APIRouter, Depends

from ..config import ServerConfig
from ..models import AnalyzeRequest, AnalyzeResponse
from ..services import analyzer

AuthDependency = Callable[..., None]


def create_analysis_router(config: ServerConfig, auth_dependency: AuthDependency) -> APIRouter:
    router = APIRouter(prefix="/api", dependencies=[Depends(auth_dependency)])

    @router.post("/analyze", response_model=AnalyzeResponse)
    def analyze_url(request: AnalyzeRequest) -> AnalyzeResponse:
        return analyzer.analyze(request, config_dir=config.config_dir)

    return router
