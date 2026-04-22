"""
src/hwp_parser.py
=================
HWP/HWPX 파일에서 텍스트를 추출하는 파서 모듈.

파싱 전략 (우선순위 순):
1. HwpForge CLI (hwpforge) — Rust 기반 고품질 파서
   - HWPX → Markdown 직접 변환 (구조·수식·표 보존)
   - HWP5 → HWPX → Markdown 2단계 변환
   - 설치: cargo install hwpforge-bindings-cli
           (Docker 이미지에는 이미 포함됨)

2. 폴백 — HwpForge 미설치 시
   - HWPX: 표준 라이브러리(ZIP + XML) 파싱
   - HWP:  pyhwp 라이브러리 (pip install pyhwp)
"""

import logging
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import List, Optional


# ---------------------------------------------------------------------------
# 가용성 확인
# ---------------------------------------------------------------------------

def is_hwpforge_available() -> bool:
    """HwpForge CLI (hwpforge) 가 실행 가능한지 확인합니다."""
    try:
        r = subprocess.run(
            ['hwpforge', '--version'],
            capture_output=True,
            timeout=5,
        )
        return r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def is_hwp_file(file_path: str) -> bool:
    """파일이 HWP 또는 HWPX 형식인지 확인합니다."""
    return Path(file_path).suffix.lower() in ('.hwp', '.hwpx')


# ---------------------------------------------------------------------------
# HwpForge 기반 파싱 (1순위)
# ---------------------------------------------------------------------------

def parse_to_markdown(file_path: str) -> Optional[str]:
    """
    HwpForge CLI로 HWP/HWPX → Markdown 변환을 시도합니다.

    문서 구조(제목·목록·표·수식)가 Markdown으로 보존되어
    번역 품질이 크게 향상됩니다.

    Returns:
        Markdown 문자열 — HwpForge 미설치·변환 실패 시 None
    """
    if not is_hwpforge_available():
        return None

    # cwd 를 임시 디렉토리로 변경하므로 상대 경로는 파일을 찾지 못함 → 절대 경로로 변환
    file_path = str(Path(file_path).resolve())
    ext = Path(file_path).suffix.lower()
    with tempfile.TemporaryDirectory(prefix='hwpforge_') as tmp:
        work = Path(tmp)
        try:
            if ext == '.hwpx':
                return _hwpx_to_markdown(file_path, work)
            else:                                        # .hwp (HWP5)
                return _hwp5_to_markdown(file_path, work)
        except Exception as exc:
            logging.warning(
                f"[HwpForge] '{Path(file_path).name}' 변환 실패: {exc}"
            )
            return None


def _run(cmd: list, **kwargs) -> subprocess.CompletedProcess:
    """subprocess.run 래퍼 — 기본 옵션 적용."""
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        timeout=120,
        **kwargs,
    )


def _hwpx_to_markdown(file_path: str, work: Path) -> str:
    """hwpforge to-md 로 HWPX → Markdown 변환."""
    stem = Path(file_path).stem
    md_out = work / f"{stem}.md"

    # --output <OUTPUT> <INPUT> 형식 (HwpForge CLI 규격)
    r = _run(['hwpforge', 'to-md', '--output', str(md_out), str(file_path)])
    if r.returncode == 0 and md_out.exists():
        content = md_out.read_text(encoding='utf-8')
        if content.strip():
            return content

    # stdout 출력 시도 (--output 미지원 구버전 대비)
    r = _run(['hwpforge', 'to-md', str(file_path)])
    if r.returncode == 0 and r.stdout.strip():
        return r.stdout

    raise RuntimeError(
        f"hwpforge to-md 실패 (rc={r.returncode}): {r.stderr.strip()[:200]}"
    )


def _hwp5_to_markdown(file_path: str, work: Path) -> str:
    """hwpforge convert-hwp5 → to-md 로 HWP5 → HWPX → Markdown 2단계 변환."""
    stem = Path(file_path).stem
    hwpx_out = work / f"{stem}.hwpx"

    # --output <OUTPUT> <INPUT> 형식 (HwpForge CLI 규격, --output 필수)
    r = _run(
        ['hwpforge', 'convert-hwp5', '--output', str(hwpx_out), str(file_path)],
        cwd=str(work),
    )
    if r.returncode != 0:
        raise RuntimeError(
            f"hwpforge convert-hwp5 실패 (rc={r.returncode}): "
            f"{r.stderr.strip()[:200]}"
        )

    # 출력 파일 탐색 (경로 불일치 대비)
    if not hwpx_out.exists():
        candidates = sorted(work.glob("*.hwpx"))
        if not candidates:
            raise RuntimeError(
                "HWP5 → HWPX 변환 후 출력 파일을 찾을 수 없습니다."
            )
        hwpx_out = candidates[0]

    return _hwpx_to_markdown(str(hwpx_out), work)


# ---------------------------------------------------------------------------
# 의미적 HWPX 파서 — rhwp 분석 기반 (2순위)
# ---------------------------------------------------------------------------

_HEAD_TYPE_MAP = {
    '0': 'none',    'NONE': 'none',
    '1': 'outline', 'OUTLINE': 'outline',
    '2': 'number',  'NUMBER': 'number',
    '3': 'bullet',  'BULLET': 'bullet',
}
_OUTLINE_MARKS = ['#', '##', '###', '####', '#####', '######', '#######']
_HEADING_STYLE_RE = re.compile(
    r'^(제목|표제|머리말|Heading|Head|Title)\s*(\d)',
    re.IGNORECASE,
)


def _lname(tag: str) -> str:
    """Strip XML namespace prefix from a tag string."""
    return tag.split('}')[-1] if '}' in tag else tag


def _attr(elem: ET.Element, *local_names: str) -> Optional[str]:
    """Return first attribute value matching any of the given local names (ignores namespace)."""
    for key, val in elem.attrib.items():
        if (_lname(key)) in local_names:
            return val
    return None


def _infer_heading_from_style_name(name: str) -> tuple:
    """Infer (head_type, 0-indexed level) from a style name string, or ('none', 0)."""
    m = _HEADING_STYLE_RE.match(name.strip())
    if m:
        return 'outline', max(0, int(m.group(2)) - 1)
    return 'none', 0


def _collect_para_shapes(root: ET.Element, out: dict) -> None:
    """Populate *out* with {id: {head_type, level}} from <paraPr> elements."""
    for elem in root.iter():
        if _lname(elem.tag) not in ('paraPr', 'paraShape'):
            continue
        id_val = _attr(elem, 'id', 'ID')
        if id_val is None:
            continue
        raw_ht, raw_lv = '0', '0'
        for child in elem:
            if _lname(child.tag) == 'heading':
                raw_ht = _attr(child, 'type', 'Type', 'headType') or raw_ht
                raw_lv = _attr(child, 'level', 'Level') or raw_lv
                break
        out[id_val] = {
            'head_type': _HEAD_TYPE_MAP.get(raw_ht.upper(), 'none'),
            'level': int(raw_lv) if raw_lv.isdigit() else 0,
        }


def _collect_styles(root: ET.Element, out: dict) -> None:
    """Populate *out* with {id: {name, paraPrIDRef}} from <style> elements."""
    for elem in root.iter():
        if _lname(elem.tag) != 'style':
            continue
        id_val = _attr(elem, 'id', 'ID')
        if id_val is None:
            continue
        out[id_val] = {
            'name': _attr(elem, 'name', 'Name') or '',
            'paraPrIDRef': _attr(elem, 'paraPrIDRef', 'paraPrId', 'paraPrRef') or '',
        }


def _parse_hwpx_style_maps(
    z: zipfile.ZipFile,
    all_names: List[str],
) -> tuple:
    """Read all header XML files from the ZIP and return (para_shape_map, style_map)."""
    para_shape_map: dict = {}
    style_map: dict = {}
    header_files = [
        n for n in all_names
        if n.endswith('.xml')
        and any(kw in n.lower() for kw in ('header', 'settings', 'parashape', 'styles'))
        and 'section' not in n.lower()
    ]
    for hf in header_files:
        try:
            with z.open(hf) as f:
                root = ET.fromstring(f.read())
            _collect_para_shapes(root, para_shape_map)
            _collect_styles(root, style_map)
        except Exception:
            pass
    return para_shape_map, style_map


def _resolve_semantic(
    p_elem: ET.Element,
    para_shape_map: dict,
    style_map: dict,
) -> tuple:
    """
    Return (head_type, level) for a <p> element via 3-level lookup:
    1. paraPrIDRef → para_shape_map
    2. styleIDRef → style.paraPrIDRef → para_shape_map
    3. styleIDRef → style.name → name inference
    """
    para_pr_id = _attr(p_elem, 'paraPrIDRef', 'paraPrId', 'paraPrRef')
    style_id   = _attr(p_elem, 'styleIDRef',  'styleId',  'styleRef')

    if para_pr_id and para_pr_id in para_shape_map:
        shape = para_shape_map[para_pr_id]
        if shape['head_type'] != 'none':
            return shape['head_type'], shape['level']

    if style_id and style_id in style_map:
        s = style_map[style_id]
        ref = s.get('paraPrIDRef', '')
        if ref and ref in para_shape_map:
            shape = para_shape_map[ref]
            if shape['head_type'] != 'none':
                return shape['head_type'], shape['level']
        ht, lv = _infer_heading_from_style_name(s.get('name', ''))
        if ht != 'none':
            return ht, lv

    return 'none', 0


def _collect_text_nodes(elem: ET.Element, chars: List[str]) -> None:
    """Recursively collect <t> text content, skipping <tbl> subtrees."""
    for child in elem:
        if _lname(child.tag) == 'tbl':
            continue
        if _lname(child.tag) == 't' and child.text:
            chars.append(child.text)
        _collect_text_nodes(child, chars)


def _extract_para_text(elem: ET.Element) -> str:
    chars: List[str] = []
    _collect_text_nodes(elem, chars)
    return ''.join(chars).strip()


def _in_table(elem: ET.Element, parent_map: dict) -> bool:
    """Return True if any ancestor of elem is a <tbl>, <tr>, or <tc> element."""
    p = parent_map.get(elem)
    while p is not None:
        if _lname(p.tag) in ('tbl', 'tc', 'tr'):
            return True
        p = parent_map.get(p)
    return False


def _find_tbl(elem: ET.Element) -> Optional[ET.Element]:
    """Return first <tbl> descendant of elem, or None."""
    for desc in elem.iter():
        if _lname(desc.tag) == 'tbl':
            return desc
    return None


def _find_direct(elem: ET.Element, local_name: str) -> List[ET.Element]:
    return [c for c in elem if _lname(c.tag) == local_name]


def _table_to_md(tbl_elem: ET.Element) -> str:
    """Convert a <tbl> element to a Markdown table string."""
    rows: List[List[str]] = []

    tr_elems = _find_direct(tbl_elem, 'tr')
    if not tr_elems:
        for child in tbl_elem:
            tr_elems.extend(_find_direct(child, 'tr'))

    for tr in tr_elems:
        cells: List[str] = []
        for tc in _find_direct(tr, 'tc'):
            cell_parts: List[str] = []
            for p in tc:
                if _lname(p.tag) == 'p':
                    chars: List[str] = []
                    _collect_text_nodes(p, chars)
                    text = ''.join(chars).strip()
                    if text:
                        cell_parts.append(text)
            cells.append(
                ' '.join(cell_parts).replace('|', '\\|').replace('\n', ' ')
            )
        if cells:
            rows.append(cells)

    if not rows:
        return ''

    max_cols = max(len(r) for r in rows)
    rows = [r + [''] * (max_cols - len(r)) for r in rows]
    header, sep = rows[0], ['---'] * max_cols
    md_lines = [
        '| ' + ' | '.join(header) + ' |',
        '| ' + ' | '.join(sep) + ' |',
    ]
    for row in rows[1:]:
        md_lines.append('| ' + ' | '.join(row) + ' |')
    return '\n'.join(md_lines)


def _para_to_md(text: str, head_type: str, level: int, counters: dict) -> str:
    """Format a paragraph as a Markdown line based on its semantic type."""
    if head_type == 'outline':
        prefix = _OUTLINE_MARKS[min(level, 6)]
        return f'\n{prefix} {text}\n'
    if head_type == 'number':
        n = counters.get(level, 0) + 1
        counters[level] = n
        for k in list(counters):
            if k > level:
                del counters[k]
        return '  ' * level + f'{n}. {text}'
    if head_type == 'bullet':
        return '  ' * level + f'- {text}'
    return text + '\n'


def parse_hwpx_to_markdown(file_path: str) -> Optional[str]:
    """
    HWPX 파일의 의미적 구조를 Markdown으로 추출합니다.

    HwpForge 미설치 시 2순위 파서로 사용됩니다:
    - OUTLINE 단락  → Markdown 제목 (#, ##, ...)
    - NUMBER  단락  → 번호 목록  (1., 2., ...)
    - BULLET  단락  → 글머리 기호 목록 (-)
    - 표             → Markdown 테이블
    """
    try:
        with zipfile.ZipFile(file_path, 'r') as z:
            all_names = z.namelist()
            para_shape_map, style_map = _parse_hwpx_style_maps(z, all_names)

            section_files = sorted(
                n for n in all_names
                if re.match(r'Contents/section\d+\.xml', n)
            )
            if not section_files:
                section_files = sorted(
                    n for n in all_names
                    if n.endswith('.xml') and 'section' in n.lower()
                )

            md_lines: List[str] = []
            counters: dict = {}

            for sf in section_files:
                with z.open(sf) as f:
                    root = ET.fromstring(f.read())

                parent_map = {c: p for p in root.iter() for c in p}

                for elem in root.iter():
                    if _lname(elem.tag) != 'p':
                        continue
                    if _in_table(elem, parent_map):
                        continue

                    tbl = _find_tbl(elem)
                    if tbl is not None:
                        table_md = _table_to_md(tbl)
                        if table_md:
                            md_lines.append('')
                            md_lines.append(table_md)
                            md_lines.append('')
                        continue

                    text = _extract_para_text(elem)
                    if not text:
                        continue

                    head_type, level = _resolve_semantic(elem, para_shape_map, style_map)
                    md_lines.append(_para_to_md(text, head_type, level, counters))

    except zipfile.BadZipFile:
        raise ValueError(f"올바른 HWPX 파일이 아닙니다: {file_path}")
    except Exception as exc:
        logging.warning(
            f"[HWPX 의미 파서] '{Path(file_path).name}' 파싱 실패: {exc}"
        )
        return None

    result = re.sub(r'\n{3,}', '\n\n', '\n'.join(md_lines)).strip()
    return (result + '\n') if result else None


# ---------------------------------------------------------------------------
# 폴백 ① — HWPX: 표준 라이브러리 ZIP + XML
# ---------------------------------------------------------------------------

def parse_hwpx(file_path: str) -> List[str]:
    """
    HWPX 파일에서 단락 텍스트 목록을 추출합니다.

    HwpForge가 없을 때 사용하는 표준 라이브러리 기반 폴백.
    ZIP 아카이브를 열어 Contents/section*.xml 을 파싱합니다.
    """
    texts: List[str] = []
    try:
        with zipfile.ZipFile(file_path, 'r') as z:
            all_names = z.namelist()

            section_files = sorted(
                n for n in all_names if re.match(r'Contents/section\d+\.xml', n)
            )
            if not section_files:
                section_files = sorted(
                    n for n in all_names
                    if n.endswith('.xml') and 'section' in n.lower()
                )
            if not section_files:
                logging.warning(f"HWPX 섹션 파일 없음: {file_path}")

            for sf in section_files:
                with z.open(sf) as f:
                    try:
                        root = ET.fromstring(f.read())
                        texts.extend(_extract_paragraph_texts(root))
                    except ET.ParseError as exc:
                        logging.warning(f"HWPX XML 파싱 오류 ({sf}): {exc}")
    except zipfile.BadZipFile:
        raise ValueError(f"올바른 HWPX 파일이 아닙니다: {file_path}")

    return texts


def _extract_paragraph_texts(root: ET.Element) -> List[str]:
    """XML 루트에서 단락(<p>) 단위 텍스트를 수집합니다."""
    texts: List[str] = []
    for elem in root.iter():
        local = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
        if local == 'p':
            chars = []
            for child in elem.iter():
                cl = child.tag.split('}')[-1] if '}' in child.tag else child.tag
                if cl == 't' and child.text:
                    chars.append(child.text)
            para = ''.join(chars).strip()
            if para:
                texts.append(para)
    return texts


# ---------------------------------------------------------------------------
# 폴백 ② — HWP 바이너리: pyhwp
# ---------------------------------------------------------------------------

def parse_hwp(file_path: str) -> List[str]:
    """
    HWP 바이너리 파일에서 텍스트를 추출합니다.

    pyhwp(hwp5txt)를 사용합니다.
    설치: pip install pyhwp
    """
    for cmd in [
        [sys.executable, '-m', 'hwp5.hwp5txt', str(file_path)],
        ['hwp5txt', str(file_path)],
    ]:
        try:
            r = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=60,
            )
            if r.returncode == 0:
                return [ln.strip() for ln in r.stdout.split('\n') if ln.strip()]
            logging.warning(f"pyhwp 오류 ({cmd[0]}): {r.stderr.strip()[:200]}")
        except FileNotFoundError:
            continue

    raise ImportError(
        "HWP 바이너리 파일 처리를 위해 pyhwp가 필요합니다.\n"
        "설치 방법: pip install pyhwp"
    )
