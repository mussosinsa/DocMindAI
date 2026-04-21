"""
src/translation/engines/ollama.py
=================================
Ollama 로컬 LLM 번역 엔진 구현체입니다.

이 모듈은 다음 기능을 수행합니다:
1. **로컬 LLM 번역**: Ollama 서버(기본 http://localhost:11434)를 통해 번역 수행.
2. **모델 동적 선택**: 생성 시 모델명을 지정 (예: llama3.2, qwen2.5:7b, gemma3).
3. **폴백**: 오류·서버 미실행 시 Google Translate 로 폴백.

환경 변수:
    OLLAMA_BASE_URL   Ollama 서버 URL (기본: http://localhost:11434)

사용:
    translator = OllamaTranslator(model="llama3.2")
    translator.translate("Hello", "en", "ko")
"""

import json
import logging
import os
import urllib.error
import urllib.request
from typing import List

from ..base import BaseTranslator
from ..utils import LANGUAGE_NAMES
from .google import GoogleTranslator


DEFAULT_OLLAMA_URL = "http://localhost:11434"


# ---------------------------------------------------------------------------
# 서버 상태 / 모델 목록 조회 헬퍼
# ---------------------------------------------------------------------------

def get_ollama_base_url() -> str:
    """Ollama 서버 URL 을 반환합니다."""
    return os.getenv("OLLAMA_BASE_URL", DEFAULT_OLLAMA_URL).rstrip("/")


def list_ollama_models(timeout: float = 2.0) -> List[str]:
    """
    Ollama 서버에서 설치된 모델명 리스트를 조회합니다.

    서버 미실행·연결 실패 시 빈 리스트를 반환합니다 (예외는 발생시키지 않음).
    최근 수정된 모델이 먼저 오도록 정렬합니다.
    """
    url = f"{get_ollama_base_url()}/api/tags"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        models = data.get("models", []) or []
        models.sort(key=lambda m: m.get("modified_at", ""), reverse=True)
        return [m["name"] for m in models if "name" in m]
    except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError) as exc:
        logging.debug(f"Ollama 모델 조회 실패 ({url}): {exc}")
        return []
    except Exception as exc:
        logging.warning(f"Ollama 모델 조회 중 예기치 못한 오류: {exc}")
        return []


def is_ollama_available() -> bool:
    """Ollama 서버 가용성 확인."""
    url = f"{get_ollama_base_url()}/api/tags"
    try:
        with urllib.request.urlopen(url, timeout=1.5) as resp:
            return resp.status == 200
    except Exception:
        return False


# ---------------------------------------------------------------------------
# 번역 엔진
# ---------------------------------------------------------------------------

class OllamaTranslator(BaseTranslator):
    """
    Ollama 로컬 LLM 기반 번역 엔진.

    Args:
        model: Ollama 모델명 (예: "llama3.2", "qwen2.5:7b", "gemma3:4b")

    실패 시 GoogleTranslator 로 자동 폴백합니다.
    """

    def __init__(self, model: str):
        if not model:
            raise ValueError("Ollama 모델명을 지정해야 합니다.")
        self.model = model
        self.base_url = get_ollama_base_url()
        self.fallback_engine = GoogleTranslator()

    def translate(self, text: str, src: str, dest: str) -> str:
        if not text or not text.strip():
            return ""

        src_name = LANGUAGE_NAMES.get(src, src)
        dest_name = LANGUAGE_NAMES.get(dest, dest)

        prompt = (
            f"Translate the following text from {src_name} to {dest_name}.\n"
            f"Maintain technical terms and original formatting.\n"
            f"Return ONLY the translation — no explanations, no quotes, no tags.\n\n"
            f"Text:\n{text}"
        )

        payload = json.dumps({
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.2},
        }).encode("utf-8")

        req = urllib.request.Request(
            f"{self.base_url}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            result = (body.get("response") or "").strip()
            if result:
                return result
            raise RuntimeError("Ollama 응답이 비어 있습니다.")
        except Exception as exc:
            logging.error(
                f"Ollama 오류 (model={self.model} → Google 폴백): {exc}"
            )
            return self.fallback_engine.translate(text, src, dest)
