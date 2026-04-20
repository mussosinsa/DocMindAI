# =============================================================================
# DocMindAI — Document Translation Service
# =============================================================================
# 멀티스테이지 빌드:
#   Stage 1 (hwpforge-builder): Rust 툴체인으로 HwpForge CLI 컴파일
#   Stage 2 (runtime):          Python 런타임 + HwpForge 바이너리만 복사
#
# 실행 모드 (CMD 오버라이드로 선택):
#   REST API  : uvicorn api:app --host 0.0.0.0 --port 8000  (기본값)
#   Streamlit : streamlit run app.py --server.address 0.0.0.0 --server.port 8501
#   CLI       : python main.py <file> --source ko --target en
# =============================================================================


# -----------------------------------------------------------------------------
# Stage 1 — HwpForge CLI 빌드 (Rust)
# -----------------------------------------------------------------------------
FROM rust:slim AS hwpforge-builder

# 빌드 의존성 (OpenSSL 정적 링크)
RUN apt-get update && apt-get install -y --no-install-recommends \
        pkg-config \
        libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# hwpforge-bindings-cli 설치 (crates.io 미등록 → GitHub 소스에서 직접 빌드)
RUN cargo install \
        --git https://github.com/ai-screams/HwpForge \
        --bin hwpforge \
        hwpforge-bindings-cli \
    && strip /usr/local/cargo/bin/hwpforge   # 바이너리 크기 최소화


# -----------------------------------------------------------------------------
# Stage 2 — Python 런타임
# -----------------------------------------------------------------------------
FROM python:3.11-slim AS runtime

# ---------------------------------------------------------------------------
# 메타데이터
# ---------------------------------------------------------------------------
LABEL maintainer="DocMindAI" \
      description="Document translation service — PDF, DOCX, HWP/HWPX, images" \
      version="1.0.0"

# ---------------------------------------------------------------------------
# 환경 변수
# ---------------------------------------------------------------------------
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    NLTK_DATA=/app/nltk_data \
    HF_HOME=/app/.cache/huggingface \
    DOCLING_CACHE=/app/.cache/docling

WORKDIR /app

# ---------------------------------------------------------------------------
# HwpForge CLI 바이너리 복사 (Stage 1에서)
# ---------------------------------------------------------------------------
COPY --from=hwpforge-builder /usr/local/cargo/bin/hwpforge /usr/local/bin/hwpforge

# ---------------------------------------------------------------------------
# 시스템 의존성
# ---------------------------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
        # OpenCV / OpenGL (docling)
        libgl1 \
        libglib2.0-0 \
        libsm6 \
        libxrender1 \
        libxext6 \
        # PyTorch OpenMP
        libgomp1 \
        # 파일 타입 감지 (pyhwp 폴백)
        libmagic1 \
        # CJK 폰트 (한글 문서 렌더링)
        fonts-noto-cjk \
        # 헬스체크용
        curl \
    && rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------------------
# Python 의존성 (소스코드와 레이어 분리 → 캐시 효율화)
# ---------------------------------------------------------------------------
COPY requirements.txt .

# CPU-only PyTorch + torchvision — CUDA 라이브러리(~4 GB) 제외로 이미지 크기 대폭 절감
# torchvision 을 함께 CPU 인덱스에서 설치하지 않으면, docling 의존성 해소 과정에서
# PyPI 의 CUDA 버전 torchvision 이 설치되어 transformers AutoProcessor 임포트 오류 발생
RUN pip install --upgrade pip && \
    pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu && \
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
# 출력 디렉토리
# ---------------------------------------------------------------------------
RUN mkdir -p output

# ---------------------------------------------------------------------------
# 포트
# ---------------------------------------------------------------------------
EXPOSE 8000
EXPOSE 8501

# ---------------------------------------------------------------------------
# 헬스체크 (REST API 기준)
# ---------------------------------------------------------------------------
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# ---------------------------------------------------------------------------
# 기본 실행 명령: REST API
# ---------------------------------------------------------------------------
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
