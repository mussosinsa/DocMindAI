"""
src/rag_json_generator.py
=========================
RAG(Retrieval-Augmented Generation) 검색 정확도 강화를 위한 구조화 JSON 생성 모듈.

각 청크(chunk)에 다음 메타데이터를 포함합니다:
- type          : 단락 유형 (title / heading / paragraph / list_item / table / image_caption / code …)
- heading_level : 제목 계층 (1–6), 비제목은 null
- text          : 번역문 (RAG 검색 대상)
- source_text   : 원문
- page          : 페이지 번호 (PDF/DOCX), 없으면 null
- line          : 줄 번호 (텍스트/코드), 없으면 null
- section_path  : 현재 위치까지의 제목 계층 배열 ["Chapter 1", "1.1 Overview"]
- chunk_context : section_path를 " > "로 이은 문자열 — 임베딩 시 앞에 붙여 검색 정확도 향상
"""

from __future__ import annotations

import re
from typing import Iterable, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from docling_core.types.doc import DoclingDocument

_HEADING_RE = re.compile(r'^(#{1,6})\s+(.+)')
_LIST_RE    = re.compile(r'^(?:[-*+]|\d+\.)\s+')


# ---------------------------------------------------------------------------
# 공용 헬퍼
# ---------------------------------------------------------------------------

def _section_ctx(path: list) -> str:
    return " > ".join(path) if path else ""


def _make_meta(filename: str, source_lang: str, target_lang: str, timestamp: str) -> dict:
    return {
        "filename":    filename,
        "source_lang": source_lang,
        "target_lang": target_lang,
        "timestamp":   timestamp,
        "generator":   "DocMindAI",
    }


def _join_sentences(text: str, translation_map: dict) -> str:
    """
    NLTK 문장 분리 후 각 문장을 translation_map에서 조회해 이어붙입니다.
    Docling 파이프라인은 문장 단위로 번역하므로 단락 전체를 하나의 키로 찾으면
    히트하지 않습니다. 이 함수가 그 문제를 해결합니다.
    """
    try:
        import nltk
        sentences = nltk.sent_tokenize(text)
        return " ".join(translation_map.get(s, s) for s in sentences)
    except Exception:
        return translation_map.get(text.strip(), text)


# ---------------------------------------------------------------------------
# Docling 파이프라인용 RAG JSON
# ---------------------------------------------------------------------------

def generate_docling_rag_json(
    doc: "DoclingDocument",
    doc_items: list,
    translation_map: dict,
    filename: str,
    source_lang: str,
    target_lang: str,
    timestamp: str = "",
    vision_map: Optional[dict] = None,
    base_filename: str = "",
) -> dict:
    """
    DoclingDocument 아이템 리스트로부터 RAG용 JSON 딕셔너리를 생성합니다.

    section_path 규칙:
    - TITLE       → level 1, section_path = [title]
    - SECTION_HEADER → level 2, section_path = [title, section]
    """
    from docling_core.types.doc import DocItemLabel, PictureItem, TableItem, TextItem

    chunks: list[dict] = []
    section_path: list[str] = []
    current_page: Optional[int] = None
    chunk_id = 0

    def _tr(text: str) -> str:
        return _join_sentences(text, translation_map)

    for item, _level in doc_items:
        if item.prov and item.prov[0].page_no:
            current_page = item.prov[0].page_no

        # ── TextItem ──────────────────────────────────────────────────────
        if isinstance(item, TextItem):
            src = (item.text or "").strip()
            if not src:
                continue
            tgt = _tr(src)

            if item.label in (DocItemLabel.PAGE_HEADER, DocItemLabel.PAGE_FOOTER):
                continue

            if item.label == DocItemLabel.TITLE:
                section_path = [tgt or src]
                chunk = {
                    "id": chunk_id, "type": "title", "heading_level": 1,
                    "text": tgt, "source_text": src,
                    "page": current_page, "line": None,
                    "section_path": section_path[:],
                    "chunk_context": "",
                }
            elif item.label == DocItemLabel.SECTION_HEADER:
                section_path = section_path[:1] + [tgt or src]
                chunk = {
                    "id": chunk_id, "type": "heading", "heading_level": 2,
                    "text": tgt, "source_text": src,
                    "page": current_page, "line": None,
                    "section_path": section_path[:],
                    "chunk_context": _section_ctx(section_path[:-1]),
                }
            elif item.label == DocItemLabel.LIST_ITEM:
                chunk = {
                    "id": chunk_id, "type": "list_item", "heading_level": None,
                    "text": tgt, "source_text": src,
                    "page": current_page, "line": None,
                    "section_path": section_path[:],
                    "chunk_context": _section_ctx(section_path),
                }
            else:
                chunk = {
                    "id": chunk_id, "type": "paragraph", "heading_level": None,
                    "text": tgt, "source_text": src,
                    "page": current_page, "line": None,
                    "section_path": section_path[:],
                    "chunk_context": _section_ctx(section_path),
                }
            chunks.append(chunk)
            chunk_id += 1

        # ── TableItem ─────────────────────────────────────────────────────
        elif isinstance(item, TableItem):
            caption_src = (item.caption_text(doc) or "").strip()
            caption_tgt = _tr(caption_src) if caption_src else ""
            try:
                df = item.export_to_dataframe(doc)
                src_rows  = [" | ".join(str(c) for c in df.columns)]
                tgt_rows  = [" | ".join(_tr(str(c)) for c in df.columns)]
                for _, row in df.iterrows():
                    src_rows.append(" | ".join(str(v) for v in row.values))
                    tgt_rows.append(" | ".join(_tr(str(v)) for v in row.values))
                src_text = "\n".join(src_rows)
                tgt_text = "\n".join(tgt_rows)
            except Exception:
                src_text = caption_src
                tgt_text = caption_tgt

            chunks.append({
                "id": chunk_id, "type": "table", "heading_level": None,
                "text": tgt_text, "source_text": src_text,
                "caption": caption_tgt, "source_caption": caption_src,
                "page": current_page, "line": None,
                "section_path": section_path[:],
                "chunk_context": _section_ctx(section_path),
            })
            chunk_id += 1

        # ── PictureItem ───────────────────────────────────────────────────
        elif isinstance(item, PictureItem):
            caption_src = (item.caption_text(doc) or "").strip()
            caption_tgt = _tr(caption_src) if caption_src else ""

            # vision_map 조회: 키는 images/{base_filename}_picture_N.png
            pic_counter = sum(
                1 for c in chunks if c.get("type") in ("image_extracted", "image_caption")
            ) + 1
            _bfn = base_filename or filename.rsplit(".", 1)[0]
            img_rel = f"images/{_bfn}_picture_{pic_counter}.png"

            if vision_map and img_rel in vision_map:
                chunks.append({
                    "id": chunk_id, "type": "image_extracted", "heading_level": None,
                    "text": vision_map[img_rel],
                    "source_text": caption_src or img_rel,
                    "image_path": img_rel,
                    "caption": caption_tgt,
                    "page": current_page, "line": None,
                    "section_path": section_path[:],
                    "chunk_context": _section_ctx(section_path),
                })
            elif caption_src:
                chunks.append({
                    "id": chunk_id, "type": "image_caption", "heading_level": None,
                    "text": caption_tgt, "source_text": caption_src,
                    "page": current_page, "line": None,
                    "section_path": section_path[:],
                    "chunk_context": _section_ctx(section_path),
                })
            else:
                continue
            chunk_id += 1

    result = {"meta": _make_meta(filename, source_lang, target_lang, timestamp), "chunks": chunks}
    result["meta"]["total_chunks"] = len(chunks)
    return result


# ---------------------------------------------------------------------------
# 텍스트 / HWP / MinerU 파이프라인용 RAG JSON
# ---------------------------------------------------------------------------

def generate_text_rag_json(
    segments: Iterable,
    translation_map: dict,
    filename: str,
    source_lang: str,
    target_lang: str,
    timestamp: str = "",
    is_markdown: bool = False,
) -> dict:
    """
    TextSegment 리스트로부터 RAG용 JSON 딕셔너리를 생성합니다.

    Markdown 입력이면 # 마커로 제목·목록을 감지하여 section_path를 구성합니다.
    코드 파일이면 segment_type(comment / docstring / code)을 그대로 type에 사용합니다.
    """
    chunks: list[dict] = []
    section_path: list[str] = []
    chunk_id = 0

    def _tr(text: str) -> str:
        s = text.strip()
        return translation_map.get(s) or translation_map.get(text) or text

    for seg in segments:
        src = getattr(seg, "text", "")
        if not src or not src.strip():
            continue

        translatable = getattr(seg, "translatable", True)
        seg_type     = getattr(seg, "segment_type", "prose")
        line_no      = getattr(seg, "line_number",  None)

        raw = src.strip()
        tgt = _tr(raw) if translatable else raw

        # ── Markdown 제목 감지 ─────────────────────────────────────────────
        if is_markdown:
            h_match = _HEADING_RE.match(raw)
            if h_match:
                level       = len(h_match.group(1))
                heading_src = h_match.group(2).strip()
                heading_tgt = _tr(heading_src) if translatable else heading_src
                # section_path 갱신 (level에 따라 깊이 조정)
                section_path = section_path[:max(0, level - 1)] + [heading_tgt or heading_src]
                chunks.append({
                    "id": chunk_id, "type": "heading", "heading_level": level,
                    "text": heading_tgt, "source_text": heading_src,
                    "page": None, "line": line_no,
                    "section_path": section_path[:],
                    "chunk_context": _section_ctx(section_path[:-1]),
                })
                chunk_id += 1
                continue

            # 목록 항목 감지
            l_match = _LIST_RE.match(raw)
            if l_match:
                item_src = raw[l_match.end():].strip()
                item_tgt = _tr(item_src) if translatable else item_src
                chunks.append({
                    "id": chunk_id, "type": "list_item", "heading_level": None,
                    "text": item_tgt, "source_text": item_src,
                    "page": None, "line": line_no,
                    "section_path": section_path[:],
                    "chunk_context": _section_ctx(section_path),
                })
                chunk_id += 1
                continue

        # ── 코드 / 비번역 세그먼트 ────────────────────────────────────────
        if not translatable:
            chunks.append({
                "id": chunk_id, "type": seg_type, "heading_level": None,
                "text": raw, "source_text": raw,
                "page": None, "line": line_no,
                "section_path": section_path[:],
                "chunk_context": _section_ctx(section_path),
            })
            chunk_id += 1
            continue

        # ── 일반 단락 ─────────────────────────────────────────────────────
        chunk_type = "paragraph" if seg_type in ("prose", "docstring") else seg_type
        chunks.append({
            "id": chunk_id, "type": chunk_type, "heading_level": None,
            "text": tgt, "source_text": raw,
            "page": None, "line": line_no,
            "section_path": section_path[:],
            "chunk_context": _section_ctx(section_path),
        })
        chunk_id += 1

    result = {"meta": _make_meta(filename, source_lang, target_lang, timestamp), "chunks": chunks}
    result["meta"]["total_chunks"] = len(chunks)
    return result
