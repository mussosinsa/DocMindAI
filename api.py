"""
api.py
======
DocMindAI REST API 서버 (FastAPI 기반).

실행 방법:
    uvicorn api:app --host 0.0.0.0 --port 8000 --reload

API 엔드포인트:
    POST   /api/v1/translate          문서 업로드 및 번역 잡 생성
    GET    /api/v1/jobs/{job_id}      잡 상태 조회
    GET    /api/v1/jobs/{job_id}/result  번역 결과 HTML 다운로드
    GET    /api/v1/jobs               전체 잡 목록
    DELETE /api/v1/jobs/{job_id}      잡 삭제
    GET    /health                    헬스체크

사용 예시:
    # 파일 업로드
    curl -X POST http://localhost:8000/api/v1/translate \\
         -F "file=@document.pdf" \\
         -F "source_lang=en" \\
         -F "target_lang=ko" \\
         -F "engine=google"

    # 상태 조회
    curl http://localhost:8000/api/v1/jobs/{job_id}

    # 결과 다운로드
    curl -o result.html http://localhost:8000/api/v1/jobs/{job_id}/result
"""

import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Literal, Optional

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from src.core import create_converter, process_document
from src.job_manager import JobStatus, job_manager
from src.utils import inject_images

# ---------------------------------------------------------------------------
# 로깅
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# ---------------------------------------------------------------------------
# FastAPI 앱
# ---------------------------------------------------------------------------
app = FastAPI(
    title="DocMindAI REST API",
    description="문서 번역 서비스 REST API — PDF, DOCX, PPTX, HWP/HWPX, 이미지 지원",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Converter 캐시 (앱 시작 시 한 번 생성)
# ---------------------------------------------------------------------------
_converters: dict[str, object] = {}


def _get_converter(speed_mode: str = "balanced"):
    if speed_mode not in _converters:
        _converters[speed_mode] = create_converter(speed_mode=speed_mode)
    return _converters[speed_mode]


# ---------------------------------------------------------------------------
# 응답 스키마
# ---------------------------------------------------------------------------
class JobCreatedResponse(BaseModel):
    job_id: str
    status: str = "queued"
    message: str = "잡이 생성되었습니다. /api/v1/jobs/{job_id} 로 상태를 확인하세요."


class JobStatusResponse(BaseModel):
    job_id: str
    status: JobStatus
    progress: float = Field(ge=0.0, le=1.0)
    message: str
    file_name: str
    source_lang: str
    target_lang: str
    engine: str
    parser_backend: str
    error: Optional[str] = None
    created_at: str
    finished_at: Optional[str] = None


class JobListResponse(BaseModel):
    total: int
    jobs: list[JobStatusResponse]


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "1.0.0"


# ---------------------------------------------------------------------------
# 헬스체크
# ---------------------------------------------------------------------------
@app.get("/health", response_model=HealthResponse, tags=["System"])
async def health():
    """서버 상태 확인."""
    return HealthResponse()


# ---------------------------------------------------------------------------
# 번역 잡 생성
# ---------------------------------------------------------------------------
@app.post(
    "/api/v1/translate",
    response_model=JobCreatedResponse,
    status_code=202,
    tags=["Translation"],
    summary="문서 번역 잡 생성",
    description=(
        "파일을 업로드하면 백그라운드에서 번역을 시작하고 job_id를 반환합니다.\n\n"
        "지원 형식: PDF, DOCX, PPTX, HTML, PNG/JPG, HWP, HWPX, TXT, MD 등"
    ),
)
async def create_translate_job(
    file: UploadFile = File(..., description="번역할 문서 파일"),
    source_lang: str = Form("en", description="원본 언어 코드 (예: en, ko, ja)"),
    target_lang: str = Form("ko", description="번역 대상 언어 코드 (예: ko, en)"),
    engine: str = Form(
        "google",
        description="번역 엔진 (google | deepl | gemini | openai | nllb | nllb-koen | qwen-0.6b | lfm2 | lfm2-koen-mt | yanolja)",
    ),
    max_workers: int = Form(4, ge=1, le=16, description="병렬 번역 워커 수"),
    speed_mode: Literal["balanced", "fast"] = Form(
        "balanced", description="Docling 속도 모드 (balanced | fast)"
    ),
    parser_backend: Literal["docling", "mineru"] = Form(
        "docling",
        description="문서 파서 백엔드 (docling | mineru). MinerU는 pip install mineru[all] 필요",
    ),
    mineru_backend: Literal["pipeline", "vlm-auto-engine", "hybrid-auto-engine"] = Form(
        "pipeline",
        description="MinerU 엔진 (parser_backend=mineru 일 때만 적용)",
    ),
):
    # 임시 파일 저장
    suffix = Path(file.filename or "upload").suffix or ".bin"
    tmp_dir = tempfile.mkdtemp(prefix="docmind_upload_")
    tmp_path = Path(tmp_dir) / (Path(file.filename or "upload").name)

    try:
        content = await file.read()
        tmp_path.write_bytes(content)
    except Exception as exc:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail=f"파일 읽기 실패: {exc}")

    # 잡 등록
    job_id = job_manager.create_job(
        file_name=file.filename or "unknown",
        source_lang=source_lang,
        target_lang=target_lang,
        engine=engine,
        parser_backend=parser_backend,
    )

    progress_cb = job_manager.make_progress_cb(job_id)

    def _run():
        try:
            converter = _get_converter(speed_mode)
            result = process_document(
                file_path=str(tmp_path),
                converter=converter,
                source_lang=source_lang,
                dest_lang=target_lang,
                engine=engine,
                max_workers=max_workers,
                progress_cb=progress_cb,
                parser_backend=parser_backend,
                mineru_backend=mineru_backend,
            )
            return result
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    job_manager.run_in_background(job_id, _run)

    return JobCreatedResponse(job_id=job_id)


# ---------------------------------------------------------------------------
# 잡 상태 조회
# ---------------------------------------------------------------------------
@app.get(
    "/api/v1/jobs/{job_id}",
    response_model=JobStatusResponse,
    tags=["Translation"],
    summary="잡 상태 조회",
)
async def get_job_status(job_id: str):
    """job_id에 해당하는 번역 잡의 현재 상태와 진행률을 반환합니다."""
    job = job_manager.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="잡을 찾을 수 없습니다.")
    return _job_to_response(job)


# ---------------------------------------------------------------------------
# 결과 다운로드
# ---------------------------------------------------------------------------
@app.get(
    "/api/v1/jobs/{job_id}/result",
    tags=["Translation"],
    summary="번역 결과 HTML 다운로드",
    response_class=FileResponse,
)
async def download_result(job_id: str):
    """
    완료된 잡의 번역 결과 HTML 파일을 반환합니다.
    이미지가 Base64로 내장된 단일 HTML 파일입니다.
    """
    job = job_manager.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="잡을 찾을 수 없습니다.")
    if job.status == JobStatus.PROCESSING or job.status == JobStatus.QUEUED:
        raise HTTPException(status_code=202, detail="아직 처리 중입니다. 잠시 후 다시 시도하세요.")
    if job.status == JobStatus.ERROR:
        raise HTTPException(status_code=500, detail=f"처리 오류: {job.error}")
    if not job.result_path or not Path(job.result_path).exists():
        raise HTTPException(status_code=404, detail="결과 파일이 존재하지 않습니다.")

    html_path = Path(job.result_path)
    output_dir = Path(job.output_dir) if job.output_dir else html_path.parent

    # 이미지를 Base64로 내장하여 단일 파일 제공
    html_content = html_path.read_text(encoding="utf-8")
    html_content = inject_images(html_content, output_dir)

    # 임시 파일로 저장 후 응답
    result_filename = f"{Path(job.file_name).stem}_translated.html"
    tmp_result = Path(tempfile.mktemp(suffix=".html"))
    tmp_result.write_text(html_content, encoding="utf-8")

    return FileResponse(
        path=str(tmp_result),
        media_type="text/html",
        filename=result_filename,
        background=None,
    )


# ---------------------------------------------------------------------------
# 잡 목록
# ---------------------------------------------------------------------------
@app.get(
    "/api/v1/jobs",
    response_model=JobListResponse,
    tags=["Translation"],
    summary="전체 잡 목록 조회",
)
async def list_jobs(limit: int = 50):
    """최근 잡 목록을 반환합니다 (최신순)."""
    jobs = job_manager.list_jobs()[:limit]
    return JobListResponse(
        total=len(jobs),
        jobs=[_job_to_response(j) for j in jobs],
    )


# ---------------------------------------------------------------------------
# 잡 삭제
# ---------------------------------------------------------------------------
@app.delete(
    "/api/v1/jobs/{job_id}",
    status_code=204,
    tags=["Translation"],
    summary="잡 삭제",
)
async def delete_job(job_id: str):
    """잡과 관련 메타데이터를 삭제합니다. (결과 파일은 output/ 디렉토리에 유지됩니다)"""
    if not job_manager.delete(job_id):
        raise HTTPException(status_code=404, detail="잡을 찾을 수 없습니다.")


# ---------------------------------------------------------------------------
# 내부 헬퍼
# ---------------------------------------------------------------------------
def _job_to_response(job) -> JobStatusResponse:
    return JobStatusResponse(
        job_id=job.id,
        status=job.status,
        progress=job.progress,
        message=job.message,
        file_name=job.file_name,
        source_lang=job.source_lang,
        target_lang=job.target_lang,
        engine=job.engine,
        parser_backend=job.parser_backend,
        error=job.error,
        created_at=job.created_at.isoformat(),
        finished_at=job.finished_at.isoformat() if job.finished_at else None,
    )


# ---------------------------------------------------------------------------
# 직접 실행 시
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "api:app",
        host=os.getenv("API_HOST", "0.0.0.0"),
        port=int(os.getenv("API_PORT", "8000")),
        reload=bool(os.getenv("API_RELOAD", "false").lower() == "true"),
        workers=int(os.getenv("API_WORKERS", "1")),
    )
