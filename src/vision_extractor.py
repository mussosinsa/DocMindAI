"""
src/vision_extractor.py
=======================
Ollama 멀티모달 모델을 사용한 이미지/도형 텍스트 추출 모듈.

Docling PictureItem(그림, 도형, 차트)에서 이미지를 렌더링한 뒤,
원격 Ollama Vision 모델(기본: gemma4:e4b)에 보내 텍스트·내용을 추출합니다.

반환 구조 (vision_map):
    {image_relative_path: extracted_text}
    예: {"images/doc_picture_1.png": "이 도형은 3단계 프로세스를 나타냅니다..."}

추출에 실패하거나 모델이 없으면 해당 키가 없으므로 기존 이미지 표시로 폴백됩니다.
"""

from __future__ import annotations

import base64
import io
import logging
from pathlib import Path
from typing import Optional, TYPE_CHECKING

import requests

if TYPE_CHECKING:
    from docling_core.types.doc import DoclingDocument

DEFAULT_VISION_MODEL = "gemma4:e4b"

_EXTRACT_PROMPT = (
    "이 이미지에서 모든 텍스트, 숫자, 표, 다이어그램의 내용을 추출하고 설명해 주세요. "
    "도형이나 흐름도가 있다면 그 구조와 내용을 텍스트로 상세히 설명해 주세요. "
    "원본 언어 그대로 출력하세요."
)


# ---------------------------------------------------------------------------
# Ollama Vision API 호출
# ---------------------------------------------------------------------------

def extract_text_from_pil(
    pil_image,
    ollama_base_url: str,
    model: str = DEFAULT_VISION_MODEL,
    timeout: float = 60.0,
) -> str:
    """
    PIL 이미지를 Ollama Vision 모델에 보내 텍스트/내용을 추출합니다.

    Args:
        pil_image: PIL.Image 객체
        ollama_base_url: Ollama 서버 URL (예: "http://localhost:11434")
        model: 사용할 모델 이름
        timeout: 요청 타임아웃(초)

    Returns:
        추출된 텍스트 문자열. 실패 시 빈 문자열.
    """
    try:
        buf = io.BytesIO()
        pil_image.save(buf, format="PNG")
        img_b64 = base64.b64encode(buf.getvalue()).decode("ascii")

        url = ollama_base_url.rstrip("/") + "/api/generate"
        payload = {
            "model": model,
            "prompt": _EXTRACT_PROMPT,
            "images": [img_b64],
            "stream": False,
        }
        resp = requests.post(url, json=payload, timeout=timeout)
        resp.raise_for_status()
        text = resp.json().get("response", "").strip()
        return text
    except requests.exceptions.ConnectionError:
        logging.warning(f"[Vision] Ollama 서버 연결 실패: {ollama_base_url}")
    except requests.exceptions.Timeout:
        logging.warning(f"[Vision] Ollama 요청 시간 초과 (model={model})")
    except Exception as exc:
        logging.warning(f"[Vision] 이미지 텍스트 추출 실패: {exc}")
    return ""


def extract_text_from_path(
    image_path: Path,
    ollama_base_url: str,
    model: str = DEFAULT_VISION_MODEL,
    timeout: float = 60.0,
) -> str:
    """저장된 이미지 파일에서 텍스트를 추출합니다."""
    try:
        from PIL import Image
        with Image.open(image_path) as img:
            return extract_text_from_pil(img, ollama_base_url, model, timeout)
    except Exception as exc:
        logging.warning(f"[Vision] 이미지 파일 읽기 실패 ({image_path.name}): {exc}")
        return ""


# ---------------------------------------------------------------------------
# 배치 추출 — Docling PictureItem 전체 처리
# ---------------------------------------------------------------------------

def extract_picture_texts(
    doc_items: list,
    doc: "DoclingDocument",
    output_dir: Path,
    base_filename: str,
    ollama_base_url: str,
    model: str = DEFAULT_VISION_MODEL,
    progress_cb=None,
) -> dict[str, str]:
    """
    doc_items 에서 PictureItem을 찾아 이미지를 저장하고 텍스트를 추출합니다.

    Args:
        doc_items: (DocItem, level) 튜플 리스트
        doc: DoclingDocument
        output_dir: 이미지 저장 디렉토리
        base_filename: 파일명 접두사
        ollama_base_url: Ollama 서버 URL
        model: Vision 모델 이름
        progress_cb: 선택적 진행률 콜백 (ratio, msg)

    Returns:
        {image_relative_path: extracted_text}
        예: {"images/doc_picture_1.png": "추출된 텍스트..."}
    """
    try:
        from docling_core.types.doc import PictureItem
    except ImportError:
        return {}

    images_dir = output_dir / "images"
    images_dir.mkdir(exist_ok=True)

    picture_items = [
        (item, lvl) for item, lvl in doc_items
        if isinstance(item, PictureItem)
    ]
    if not picture_items:
        return {}

    vision_map: dict[str, str] = {}
    counter = 0

    for idx, (item, _) in enumerate(picture_items):
        if not hasattr(item, "get_image"):
            continue
        pil_img = item.get_image(doc)
        if pil_img is None:
            continue

        counter += 1
        filename  = f"{base_filename}_picture_{counter}.png"
        img_rel   = f"images/{filename}"
        img_abs   = output_dir / img_rel

        # 이미지 저장 (아직 없으면 저장)
        if not img_abs.exists():
            try:
                pil_img.save(img_abs, "PNG")
            except Exception as exc:
                logging.warning(f"[Vision] 이미지 저장 실패 ({filename}): {exc}")
                continue

        if progress_cb:
            ratio = (idx + 1) / len(picture_items)
            progress_cb(ratio, f"🔍 이미지 텍스트 추출 중 ({idx+1}/{len(picture_items)})...")

        logging.info(f"[Vision] {filename} → {model} 텍스트 추출 시작")
        text = extract_text_from_path(img_abs, ollama_base_url, model)
        if text:
            vision_map[img_rel] = text
            logging.info(f"[Vision] {filename} 추출 완료 ({len(text)}자)")
        else:
            logging.info(f"[Vision] {filename} 추출 결과 없음 (이미지 표시로 폴백)")

    return vision_map


# ---------------------------------------------------------------------------
# 가용성 확인
# ---------------------------------------------------------------------------

def is_vision_model_available(
    ollama_base_url: str,
    model: str = DEFAULT_VISION_MODEL,
    timeout: float = 5.0,
) -> bool:
    """Ollama 서버에 Vision 모델이 로드되어 있는지 확인합니다."""
    try:
        resp = requests.get(
            ollama_base_url.rstrip("/") + "/api/tags",
            timeout=timeout,
        )
        if resp.status_code == 200:
            names = [m.get("name", "") for m in resp.json().get("models", [])]
            return any(model in n for n in names)
    except Exception:
        pass
    return False
