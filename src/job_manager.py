"""
src/job_manager.py
==================
REST API용 백그라운드 잡(Job) 관리 모듈.

스레드 안전한 잡 큐를 제공합니다:
- 파일 업로드 → job_id 발급 → 백그라운드 처리 → 결과 다운로드
"""

import threading
import uuid
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Optional, Callable


class JobStatus(str, Enum):
    QUEUED     = "queued"
    PROCESSING = "processing"
    DONE       = "done"
    ERROR      = "error"


@dataclass
class Job:
    id: str
    status: JobStatus = JobStatus.QUEUED
    progress: float = 0.0
    message: str = "대기 중..."
    result_path: Optional[Path] = None   # 결과 HTML 파일 경로
    md_path: Optional[Path] = None       # 번역 결과 Markdown 파일 경로
    output_dir: Optional[Path] = None    # 결과 디렉토리
    error: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    finished_at: Optional[datetime] = None
    # 요청 메타데이터 (상태 조회 응답용)
    file_name: str = ""
    source_lang: str = ""
    target_lang: str = ""
    engine: str = ""
    parser_backend: str = "docling"


class JobManager:
    """스레드 안전 잡 관리자."""

    def __init__(self, max_jobs: int = 200, ttl_hours: int = 24):
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._max_jobs = max_jobs
        self._ttl = timedelta(hours=ttl_hours)

        # 만료 잡 주기적 정리 (1시간마다)
        cleaner = threading.Thread(target=self._cleanup_loop, daemon=True)
        cleaner.start()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_job(self, **meta) -> str:
        """새 잡을 등록하고 job_id를 반환합니다."""
        job_id = str(uuid.uuid4())
        job = Job(id=job_id, **meta)
        with self._lock:
            self._jobs[job_id] = job
        return job_id

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def list_jobs(self) -> list[Job]:
        with self._lock:
            return sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)

    def delete(self, job_id: str) -> bool:
        with self._lock:
            if job_id in self._jobs:
                del self._jobs[job_id]
                return True
            return False

    def run_in_background(self, job_id: str, fn: Callable[[], dict]) -> None:
        """fn을 백그라운드 스레드에서 실행하고 결과를 잡에 저장합니다."""
        t = threading.Thread(target=self._run, args=(job_id, fn), daemon=True)
        t.start()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _update(self, job_id: str, **kwargs) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job:
                for k, v in kwargs.items():
                    setattr(job, k, v)

    def make_progress_cb(self, job_id: str) -> Callable[[float, str], None]:
        """process_document()에 넘길 진행률 콜백을 반환합니다."""
        def _cb(ratio: float, msg: str):
            self._update(job_id, progress=round(ratio, 3), message=msg)
        return _cb

    def _run(self, job_id: str, fn: Callable[[], dict]) -> None:
        self._update(job_id, status=JobStatus.PROCESSING, message="처리 시작...")
        try:
            result = fn()
            if result:
                self._update(
                    job_id,
                    status=JobStatus.DONE,
                    progress=1.0,
                    message="완료",
                    result_path=result.get("html_path"),
                    md_path=result.get("md_path"),
                    output_dir=result.get("output_dir"),
                    finished_at=datetime.utcnow(),
                )
            else:
                self._update(
                    job_id,
                    status=JobStatus.ERROR,
                    progress=1.0,
                    message="처리 실패 (결과 없음)",
                    error="process_document returned empty result",
                    finished_at=datetime.utcnow(),
                )
        except Exception as exc:
            logging.exception(f"[JobManager] job {job_id} 오류")
            self._update(
                job_id,
                status=JobStatus.ERROR,
                progress=1.0,
                message=f"오류: {exc}",
                error=str(exc),
                finished_at=datetime.utcnow(),
            )

    def _cleanup_loop(self) -> None:
        while True:
            time.sleep(3600)
            cutoff = datetime.utcnow() - self._ttl
            with self._lock:
                expired = [
                    jid for jid, j in self._jobs.items()
                    if j.created_at < cutoff
                ]
                for jid in expired:
                    del self._jobs[jid]
            if expired:
                logging.info(f"[JobManager] 만료 잡 {len(expired)}개 정리 완료")


# 싱글턴 인스턴스 (api.py에서 import해서 사용)
job_manager = JobManager()
