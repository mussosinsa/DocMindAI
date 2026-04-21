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
