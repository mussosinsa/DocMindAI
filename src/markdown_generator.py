"""
src/markdown_generator.py
=========================
번역 결과를 Markdown(.md) 파일로 생성하는 모듈.

각 처리 파이프라인(Docling / 텍스트 / HWP / MinerU)의 내부 데이터
(`doc_items` + `translation_map` 또는 `segments` + `translation_map`)를
Markdown 문자열로 직렬화한다.

핵심 원칙:
- 번역문(target)만 출력한다. 원문은 포함하지 않는다.
- 표·이미지 등 구조 요소는 가능한 Markdown으로 보존한다.
- 수식(LaTeX)은 블록 수식(`$$...$$`)으로 감싼다.
"""

from __future__ import annotations

import html as _html_module
import logging
import re
from pathlib import Path
from typing import Iterable, Optional, TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from docling_core.types.doc import DoclingDocument, TableItem


# ---------------------------------------------------------------------------
# Docling 파이프라인용 Markdown 생성
# ---------------------------------------------------------------------------

def generate_docling_markdown(
    doc: "DoclingDocument",
    doc_items: list,
    translation_map: dict,
    output_dir: Path,
    base_filename: str,
) -> str:
    """
    DoclingDocument 아이템과 번역 맵을 Markdown 문자열로 직렬화한다.

    Args:
        doc: 원본 DoclingDocument (캡션·DataFrame 참조)
        doc_items: (DocItem, level) 튜플 리스트
        translation_map: {원문: 번역문} 매핑
        output_dir: 이미지 저장 위치 (이미 HTML 생성 단계에서 저장됐을 수 있음)
        base_filename: 이미지 파일명 접두사

    Returns:
        Markdown 문자열
    """
    # 지연 import — docling이 없는 환경(HTML 폴백만 사용)에서도 모듈 로드 가능하도록
    from docling_core.types.doc import (
        DocItemLabel,
        PictureItem,
        TableItem,
        TextItem,
    )
    from src.html_generator import format_formula_for_mathjax, is_formula_text
    from src.utils import save_and_get_image_path

    lines: list[str] = []
    counters = {"table": 0, "picture": 0}
    current_page = -1

    def _tr(text: str) -> str:
        """번역문 조회. 번역 실패(None/빈값) 시 원문 그대로."""
        if not text:
            return ""
        translated = translation_map.get(text)
        return translated if translated else text

    for item, _level in doc_items:
        # 페이지 마커
        item_page = -1
        if item.prov and item.prov[0].page_no:
            item_page = item.prov[0].page_no
        if item_page > 0 and item_page != current_page:
            if lines and lines[-1] != "":
                lines.append("")
            lines.append(f"<!-- Page {item_page} -->")
            lines.append("")
            current_page = item_page

        if isinstance(item, TextItem):
            text = (item.text or "").strip()
            if not text:
                continue

            # 수식 — 번역하지 않고 그대로 MathJax 블록으로 출력
            if is_formula_text(text):
                lines.append("")
                lines.append(format_formula_for_mathjax(text))
                lines.append("")
                continue

            translated = _tr(text).strip()
            if not translated:
                continue

            if item.label == DocItemLabel.TITLE:
                lines.append("")
                lines.append(f"# {translated}")
                lines.append("")
            elif item.label == DocItemLabel.SECTION_HEADER:
                lines.append("")
                lines.append(f"## {translated}")
                lines.append("")
            elif item.label == DocItemLabel.LIST_ITEM:
                lines.append(f"- {translated}")
            elif item.label in (DocItemLabel.PAGE_HEADER, DocItemLabel.PAGE_FOOTER):
                continue
            else:
                lines.append(translated)
                lines.append("")

        elif isinstance(item, (TableItem, PictureItem)):
            image_path = save_and_get_image_path(
                item, doc, output_dir, base_filename, counters
            )
            caption = (item.caption_text(doc) or "").strip()
            translated_caption = _tr(caption).strip() if caption else ""
            alt_text = "table" if isinstance(item, TableItem) else "image"

            if image_path:
                lines.append("")
                lines.append(f"![{translated_caption or alt_text}]({image_path})")
                if translated_caption:
                    lines.append("")
                    lines.append(f"*{translated_caption}*")
                lines.append("")

            # 표는 Markdown 테이블로도 내보낸다 (셀 번역 반영)
            if isinstance(item, TableItem):
                table_md = _table_to_markdown(item, doc, _tr)
                if table_md:
                    lines.append("")
                    lines.append(table_md)
                    lines.append("")

    return _collapse_blank_lines("\n".join(lines)).strip() + "\n"


def _table_to_markdown(item: "TableItem", doc: "DoclingDocument", tr) -> Optional[str]:
    """TableItem → Markdown table (번역된 셀)."""
    try:
        df = item.export_to_dataframe(doc)
    except Exception as e:
        logging.warning(f"[Markdown] 표 변환 실패(무시): {e}")
        return None

    if df is None or df.empty:
        return None

    def _cell(v) -> str:
        s = "" if v is None else str(v)
        s = s.strip()
        return tr(s).replace("|", "\\|").replace("\n", " ").strip() if s else ""

    headers = [_cell(c) for c in df.columns]
    sep = ["---"] * len(headers)

    body = []
    for _, row in df.iterrows():
        body.append([_cell(v) for v in row.values])

    lines = ["| " + " | ".join(headers) + " |",
             "| " + " | ".join(sep) + " |"]
    for row in body:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 텍스트 / HWP / MinerU 파이프라인용 Markdown 생성
# ---------------------------------------------------------------------------

def generate_text_markdown(
    segments: Iterable,
    translation_map: dict,
    is_markdown: bool = False,
) -> str:
    """
    TextSegment 리스트를 Markdown 문자열로 직렬화한다.

    - translatable=True 세그먼트는 번역문으로 대체
    - translatable=False 세그먼트(코드 블록 등)는 원문 유지
    - Markdown 입력이면 원본 구조(헤딩/리스트/강조)가 이미 보존돼 있으므로
      번역문만 교체하면 된다.

    Args:
        segments: TextSegment iterable
        translation_map: {원문: 번역문}
        is_markdown: 원본이 Markdown 문서인지 여부

    Returns:
        Markdown 문자열
    """
    def _tr(text: str) -> str:
        if not text:
            return text
        stripped = text.strip()
        if not stripped:
            return text
        translated = translation_map.get(stripped)
        if translated is None:
            # 전체 본문 기준이 아닌, 개별 문장 단위로도 검사
            translated = translation_map.get(text)
        return translated if translated else text

    parts: list[str] = []
    for seg in segments:
        text = getattr(seg, "text", "")
        translatable = getattr(seg, "translatable", True)
        seg_type = getattr(seg, "segment_type", "prose")

        if not text:
            continue

        if translatable:
            out = _tr(text)
            # 산문 세그먼트는 가독성을 위해 빈 줄로 분리
            if seg_type in ("prose", "docstring"):
                parts.append(out.strip())
                parts.append("")
            else:
                parts.append(out)
        else:
            # 코드 블록/원본 코드 — 원문 그대로 유지
            parts.append(text)

    joined = "\n".join(parts) if is_markdown else "\n".join(parts)
    return _collapse_blank_lines(joined).strip() + "\n"


# ---------------------------------------------------------------------------
# 공용 헬퍼
# ---------------------------------------------------------------------------

def _collapse_blank_lines(s: str) -> str:
    """연속된 빈 줄 3개 이상 → 2개로 축약."""
    return re.sub(r"\n{3,}", "\n\n", s)


# ---------------------------------------------------------------------------
# HTML 폴백 추출기 — 저장된 HTML 파일에서 Markdown을 재구성
# ---------------------------------------------------------------------------

def markdown_from_html_file(html_path: Path) -> str:
    """
    저장된 인터랙티브 HTML 파일에서 번역문(.tgt-block)을 추출해 Markdown으로 변환.

    저장된 `.md` 파일이 없을 때(구버전 결과) 폴백으로 사용.
    """
    try:
        html_content = html_path.read_text(encoding="utf-8")
    except Exception as e:
        logging.warning(f"[Markdown] HTML 읽기 실패: {e}")
        return ""

    return markdown_from_html_content(html_content)


def markdown_from_html_content(html_content: str) -> str:
    """HTML 문자열 → Markdown (번역문 영역만)."""
    # content-container 내부만 추출
    m = re.search(
        r'<div\s+id="content-container"[^>]*>([\s\S]*?)</div>\s*<!--\s*Close content-container',
        html_content,
        re.IGNORECASE,
    )
    inner = m.group(1) if m else html_content

    lines: list[str] = []

    # 블록 단위로 스캔 (페이지 마커, 번역문 블록, 이미지+캡션, 수식)
    # full-width 블록은 <img> 태그 + 선택적 caption 으로 한 번에 매칭 (중첩 div 우회)
    block_re = re.compile(
        r'<div\s+class="page-marker"[^>]*>([\s\S]*?)</div>'
        r'|<div\s+class="formula-block"[^>]*>([\s\S]*?)</div>'
        r'|<div\s+class="full-width"[^>]*>\s*<img\s+[^>]*src="([^"]+)"[^>]*alt="([^"]*)"[^>]*>'
        r'(?:\s*<div\s+class="caption"[^>]*>([\s\S]*?)</div>)?'
        r'|<div\s+class="tgt-block([^"]*)"[^>]*>([\s\S]*?)</div>',
        re.IGNORECASE,
    )

    for m in block_re.finditer(inner):
        (page_marker, formula,
         img_src, img_alt, img_caption,
         tgt_cls, tgt_body) = m.groups()
        if page_marker is not None:
            text = _strip_tags(page_marker).strip()
            if text:
                lines.append("")
                lines.append(f"<!-- {text} -->")
                lines.append("")
        elif formula is not None:
            text = formula.strip()
            if text:
                lines.append("")
                lines.append(text)
                lines.append("")
        elif img_src is not None:
            alt = _html_module.unescape(img_alt or "image")
            caption_text = _strip_tags(img_caption).strip() if img_caption else ""
            lines.append("")
            lines.append(f"![{caption_text or alt}]({img_src})")
            if caption_text:
                lines.append("")
                lines.append(f"*{caption_text}*")
            lines.append("")
        elif tgt_body is not None:
            cls = (tgt_cls or "").strip()
            # <h1>/<h2> 감지 → 제목
            h1 = re.search(r'<h1[^>]*>([\s\S]*?)</h1>', tgt_body, re.IGNORECASE)
            h2 = re.search(r'<h2[^>]*>([\s\S]*?)</h2>', tgt_body, re.IGNORECASE)
            # 리스트 마커 감지
            is_list = 'doc-list-marker' in tgt_body or 'doc-list-item' in cls
            text = _strip_tags(tgt_body).strip()
            text = re.sub(r'^[•·]\s*', '', text)
            if not text:
                continue

            if h1:
                lines.append("")
                lines.append(f"# {_strip_tags(h1.group(1)).strip()}")
                lines.append("")
            elif h2:
                lines.append("")
                lines.append(f"## {_strip_tags(h2.group(1)).strip()}")
                lines.append("")
            elif is_list:
                lines.append(f"- {text}")
            else:
                lines.append(text)
                lines.append("")

    return _collapse_blank_lines("\n".join(lines)).strip() + "\n"


def _strip_tags(s: str) -> str:
    """간단한 HTML 태그 제거 + 엔티티 디코드."""
    s = re.sub(r'<[^>]+>', '', s)
    return _html_module.unescape(s)
