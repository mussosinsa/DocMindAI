# 설치 및 사용 가이드

이 문서는 **DocMindAI(docling-translate)**를 처음 사용하는 사용자를 위해,
로컬 환경 설치부터 Docker/REST API 연동까지 한 번에 정리한 실전 가이드입니다.

---

## 1) 사전 준비

- Python **3.10 이상**
- (선택) Docker / Docker Compose
- (선택) API 엔진 키
  - OpenAI: `OPENAI_API_KEY`
  - DeepL: `DEEPL_API_KEY`
  - Gemini: `GEMINI_API_KEY`

---

## 2) 로컬 설치

```bash
git clone https://github.com/gyunggyung/docling-translate.git
cd docling-translate
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -U pip
pip install -r requirements.txt
```

### 2-1) 환경 변수 설정 (선택)

```bash
cp .env.example .env
```

`.env` 파일에 아래처럼 키를 입력합니다.

```env
OPENAI_API_KEY=sk-...
DEEPL_API_KEY=...
GEMINI_API_KEY=...
```

> Google 번역 엔진만 사용할 경우 API 키 없이도 시작할 수 있습니다.

---

## 3) CLI 사용법

### 3-1) 기본 번역

```bash
python main.py sample.pdf
```

### 3-2) 엔진/언어 지정

```bash
python main.py sample.pdf --engine deepl --source en --target ja
```

### 3-3) Fast 모드

```bash
python main.py sample.pdf --fast
```

### 3-4) 텍스트/코드 파일 번역

```bash
python main.py README.md --source en --target ko
python main.py script.py --source ko --target en
```

실행이 완료되면 `output/` 아래에 결과 폴더와 인터랙티브 HTML이 생성됩니다.

---

## 4) Web UI 사용법 (Streamlit)

```bash
streamlit run app.py
```

브라우저에서 `http://localhost:8501` 접속 후 파일 업로드 및 옵션 선택으로 번역을 실행할 수 있습니다.

---

## 5) Docker Compose로 실행

### 5-1) 전체 서비스 실행

```bash
docker compose up --build
```

- Web UI: `http://localhost:8501`
- REST API: `http://localhost:8000`
- Swagger 문서: `http://localhost:8000/docs`

### 5-2) 백그라운드 실행/중지

```bash
docker compose up --build -d
docker compose down
```

### 5-3) 특정 서비스만 실행

```bash
# API만 실행
docker compose up --build docmindai-api

# Web UI만 실행
docker compose up --build docmindai-web
```

---

## 6) REST API 사용법

### 6-1) 헬스체크

```bash
curl http://localhost:8000/health
```

### 6-2) 파일 업로드 번역

```bash
curl -X POST "http://localhost:8000/api/v1/translate" \
  -F "file=@sample.pdf" \
  -F "source=en" \
  -F "target=ko" \
  -F "engine=google" \
  -F "workers=8" \
  -F "fast=false"
```

응답 예시:

```json
{
  "message": "success",
  "source": "en",
  "target": "ko",
  "engine": "google",
  "output_dir": "output/sample_en_to_ko_20260419_010101",
  "html_path": "output/sample_en_to_ko_20260419_010101/sample_interactive.html",
  "html_download_url": "/api/v1/results/sample_en_to_ko_20260419_010101/sample_interactive.html"
}
```

### 6-3) 결과 HTML 다운로드

```bash
curl -L "http://localhost:8000/api/v1/results/sample_en_to_ko_20260419_010101/sample_interactive.html" -o result.html
```

---

## 7) 자주 발생하는 문제

### Docker 명령이 동작하지 않음
- Docker Desktop(또는 Docker Engine) 설치 상태를 확인하세요.
- `docker --version`, `docker compose version`으로 실행 가능 여부를 먼저 점검하세요.

### OpenAI/DeepL/Gemini 엔진이 실패함
- `.env`의 API 키 값이 정확한지 확인하세요.
- 키 권한/할당량(quota) 초과 여부를 확인하세요.

### 로컬 모델이 느리거나 메모리 부족
- `--workers 1`로 낮춰 실행하세요.
- `--fast` 옵션을 함께 고려하세요.

---

## 8) 권장 시작 순서

1. 먼저 `google` 엔진으로 작은 문서(`sample.pdf`)를 테스트
2. 결과 HTML 품질 확인
3. 필요한 경우 API 키 기반 엔진(OpenAI/DeepL/Gemini) 적용
4. 외부 연동이 필요하면 REST API로 전환

이 순서로 진행하면 설치/성능/품질 이슈를 빠르게 분리해서 확인할 수 있습니다.
