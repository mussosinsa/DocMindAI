# =============================================================================
# DocMindAI — Document Translation Service
# =============================================================================
# 실행 모드 (CMD 오버라이드로 선택)
#   REST API  : uvicorn api:app --host 0.0.0.0 --port 8000
#   Streamlit : streamlit run app.py --server.address 0.0.0.0 --server.port 8501
#   CLI       : python main.py <file> --source en --target ko
# =============================================================================

FROM python:3.11-slim

# ---------------------------------------------------------------------------
# 메타데이터
# ---------------------------------------------------------------------------
LABEL maintainer="DocMindAI" \
      description="Document translation service with REST API and Streamlit UI" \
      version="1.0.0"

# ---------------------------------------------------------------------------
# 환경 변수
# ---------------------------------------------------------------------------
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # NLTK 데이터 저장 경로
    NLTK_DATA=/app/nltk_data \
    # Docling 모델 캐시 경로
    HF_HOME=/app/.cache/huggingface \
    DOCLING_CACHE=/app/.cache/docling

WORKDIR /app

# ---------------------------------------------------------------------------
# 시스템 의존성
# ---------------------------------------------------------------------------
# PDF·이미지 처리 (docling/Pillow/OpenCV), CJK 폰트, libmagic (pyhwp)
RUN apt-get update && apt-get install -y --no-install-recommends \
        # OpenCV / OpenGL
        libgl1 \
        libglib2.0-0 \
        libsm6 \
        libxrender1 \
        libxext6 \
        # PyTorch OpenMP
        libgomp1 \
        # 파일 타입 감지 (pyhwp)
        libmagic1 \
        # CJK 폰트 (한글 문서 렌더링)
        fonts-noto-cjk \
        # curl (헬스체크용)
        curl \
    && rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------------------
# Python 의존성 (소스코드와 레이어 분리 → 캐시 활용)
# ---------------------------------------------------------------------------
COPY requirements.txt .

RUN pip install --upgrade pip && \
    pip install -r requirements.txt

# ---------------------------------------------------------------------------
# NLTK 리소스 사전 다운로드
# ---------------------------------------------------------------------------
RUN python -c "\
import nltk; \
nltk.download('punkt',     download_dir='/app/nltk_data', quiet=True); \
nltk.download('punkt_tab', download_dir='/app/nltk_data', quiet=True)"

# ---------------------------------------------------------------------------
# 소스코드 복사
# ---------------------------------------------------------------------------
COPY . .

# ---------------------------------------------------------------------------
# 출력 디렉토리 생성
# ---------------------------------------------------------------------------
RUN mkdir -p output

# ---------------------------------------------------------------------------
# 포트 노출
# ---------------------------------------------------------------------------
# REST API
EXPOSE 8000
# Streamlit UI
EXPOSE 8501

# ---------------------------------------------------------------------------
# 헬스체크 (REST API 기준)
# ---------------------------------------------------------------------------
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# ---------------------------------------------------------------------------
# 기본 실행 명령: REST API
# docker-compose에서 command: 로 오버라이드 가능
# ---------------------------------------------------------------------------
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
