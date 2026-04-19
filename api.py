"""
REST API entrypoint for DocMindAI.

외부 시스템에서 파일 업로드 기반 번역을 호출할 수 있도록 FastAPI 엔드포인트를 제공합니다.
"""

from __future__ import annotations

import logging
import shutil
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from src.core import create_converter, process_document

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

app = FastAPI(
    title="DocMindAI REST API",
    version="1.0.0",
    description="문서 번역 파이프라인을 외부에서 호출하기 위한 REST API",
)

UPLOAD_DIR = Path("uploads")
OUTPUT_DIR = Path("output")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

SUPPORTED_ENGINES = {
    "google",
    "deepl",
    "gemini",
    "openai",
    "qwen-0.6b",
    "lfm2",
    "lfm2-koen-mt",
    "nllb",
    "nllb-koen",
    "yanolja",
}


@lru_cache(maxsize=2)
def get_converter(speed_mode: str):
    return create_converter(speed_mode=speed_mode)


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.post("/api/v1/translate")
async def translate_document(
    file: UploadFile = File(...),
    source: str = Form("en"),
    target: str = Form("ko"),
    engine: str = Form("google"),
    workers: int = Form(8),
    fast: bool = Form(False),
):
    engine = engine.lower().strip()
    if engine not in SUPPORTED_ENGINES:
        raise HTTPException(status_code=400, detail=f"Unsupported engine: {engine}")

    safe_name = Path(file.filename or "uploaded_file").name
    if not safe_name:
        raise HTTPException(status_code=400, detail="Invalid filename")

    saved_path = UPLOAD_DIR / safe_name
    try:
        with saved_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to save upload: {exc}") from exc
    finally:
        file.file.close()

    speed_mode = "fast" if fast else "balanced"
    converter = get_converter(speed_mode)

    worker_count = workers
    if engine in {"qwen-0.6b", "lfm2", "lfm2-koen-mt", "nllb", "nllb-koen", "yanolja"} and worker_count == 8:
        worker_count = 1

    try:
        result = process_document(
            file_path=str(saved_path),
            converter=converter,
            source_lang=source,
            dest_lang=target,
            engine=engine,
            max_workers=worker_count,
            ui_lang="en",
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Translation failed: {exc}") from exc

    if not result:
        raise HTTPException(status_code=500, detail="Translation failed with empty result")

    output_dir = Path(result["output_dir"])
    html_path = Path(result["html_path"])

    return {
        "message": "success",
        "source": source,
        "target": target,
        "engine": engine,
        "output_dir": str(output_dir),
        "html_path": str(html_path),
        "html_download_url": f"/api/v1/results/{output_dir.name}/{html_path.name}",
    }


@app.get("/api/v1/results/{job_dir}/{file_name}")
def download_result(job_dir: str, file_name: str):
    safe_job_dir = Path(job_dir).name
    safe_file_name = Path(file_name).name

    target_path = OUTPUT_DIR / safe_job_dir / safe_file_name
    if not target_path.exists() or not target_path.is_file():
        raise HTTPException(status_code=404, detail="Result file not found")

    return FileResponse(path=target_path, filename=safe_file_name)
