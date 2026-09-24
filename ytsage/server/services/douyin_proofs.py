"""Short-lived server-owned authorization for verified Douyin downloads."""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass
from typing import Callable


DOUYIN_PROOF_TTL_SECONDS = 120


class DouyinProofError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class _Proof:
    canonical_url: str
    account_id: str | None
    expires_at: float


class DouyinDownloadProofStore:
    """Process-local proofs intentionally expire across server restarts."""

    def __init__(
        self,
        ttl_seconds: int = DOUYIN_PROOF_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.ttl_seconds = ttl_seconds
        self.clock = clock
        self._proofs: dict[str, _Proof] = {}
        self._lock = threading.Lock()

    def issue(self, canonical_url: str, account_id: str | None) -> str:
        token = secrets.token_urlsafe(32)
        now = self.clock()
        with self._lock:
            self._purge_expired(now)
            self._proofs[token] = _Proof(canonical_url, account_id, now + self.ttl_seconds)
        return token

    def consume(self, token: str | None, canonical_url: str, account_id: str | None) -> None:
        if not token:
            raise DouyinProofError(
                "douyin_analysis_required",
                "Analyze this Douyin video before creating a download task.",
            )
        now = self.clock()
        with self._lock:
            proof = self._proofs.pop(token, None)
            self._purge_expired(now)
        if proof is None:
            raise DouyinProofError(
                "douyin_proof_invalid",
                "The Douyin analysis authorization is invalid, expired, or already used.",
            )
        if proof.expires_at <= now:
            raise DouyinProofError(
                "douyin_proof_expired",
                "The Douyin analysis authorization expired. Analyze the video again.",
            )
        if proof.canonical_url != canonical_url or proof.account_id != account_id:
            raise DouyinProofError(
                "douyin_proof_mismatch",
                "The Douyin analysis authorization does not match this URL and account.",
            )

    def _purge_expired(self, now: float) -> None:
        expired = [token for token, proof in self._proofs.items() if proof.expires_at <= now]
        for token in expired:
            del self._proofs[token]
