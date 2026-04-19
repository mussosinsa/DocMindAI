"""
src/hwp_parser.py
=================
HWP/HWPX 파일에서 텍스트를 추출하는 파서 모듈.

지원 형식:
- .hwpx: ZIP 기반 XML 형식 (표준 라이브러리만으로 파싱)
- .hwp:  바이너리 OLE 형식 (pyhwp 라이브러리 필요)

pyhwp 설치: pip install pyhwp
"""

import zipfile
import xml.etree.ElementTree as ET
import re
import subprocess
import sys
import logging
from pathlib import Path
from typing import List


def is_hwp_file(file_path: str) -> bool:
    """파일이 HWP 또는 HWPX 형식인지 확인합니다."""
    ext = Path(file_path).suffix.lower()
    return ext in ('.hwp', '.hwpx')


def parse_hwpx(file_path: str) -> List[str]:
    """HWPX 파일에서 단락 텍스트 목록을 추출합니다.

    HWPX는 ZIP 아카이브 내에 XML 파일을 포함하는 형식입니다.
    추가 의존성 없이 표준 라이브러리만으로 파싱합니다.

    Args:
        file_path: HWPX 파일 경로

    Returns:
        단락 텍스트 목록

    Raises:
        ValueError: 올바른 HWPX 파일이 아닌 경우
    """
    texts = []
    try:
        with zipfile.ZipFile(file_path, 'r') as z:
            all_names = z.namelist()

            # 섹션 파일 탐색: Contents/section0.xml, section1.xml, ...
            section_files = sorted([
                name for name in all_names
                if re.match(r'Contents/section\d+\.xml', name)
            ])

            if not section_files:
                # 대안: 'section'이 포함된 모든 XML 파일 탐색
                section_files = sorted([
                    name for name in all_names
                    if name.endswith('.xml') and 'section' in name.lower()
                ])

            if not section_files:
                logging.warning(f"HWPX 섹션 파일을 찾을 수 없습니다: {file_path}")

            for section_file in section_files:
                with z.open(section_file) as f:
                    try:
                        root = ET.fromstring(f.read())
                        texts.extend(_extract_paragraph_texts(root))
                    except ET.ParseError as e:
                        logging.warning(f"HWPX XML 파싱 오류 ({section_file}): {e}")
    except zipfile.BadZipFile:
        raise ValueError(f"올바른 HWPX 파일이 아닙니다: {file_path}")

    return texts


def _extract_paragraph_texts(root: ET.Element) -> List[str]:
    """XML 루트 요소에서 단락(p) 단위 텍스트를 추출합니다.

    HWPX 단락 구조:
      <hp:p> (단락)
        <hp:run> (텍스트 런)
          <hp:t> (텍스트 내용)
    """
    texts = []

    for elem in root.iter():
        local_tag = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag

        if local_tag == 'p':
            # 단락 내 모든 <hp:t> 텍스트 수집
            para_chars = []
            for child in elem.iter():
                child_local = child.tag.split('}')[-1] if '}' in child.tag else child.tag
                if child_local == 't' and child.text:
                    para_chars.append(child.text)

            para_text = ''.join(para_chars).strip()
            if para_text:
                texts.append(para_text)

    return texts


def parse_hwp(file_path: str) -> List[str]:
    """HWP 바이너리 파일에서 텍스트를 추출합니다.

    pyhwp 라이브러리를 통해 텍스트를 추출합니다.
    pyhwp 설치: pip install pyhwp

    Args:
        file_path: HWP 파일 경로

    Returns:
        단락 텍스트 목록

    Raises:
        ImportError: pyhwp가 설치되지 않은 경우
    """
    # 1순위: python -m hwp5.hwp5txt (현재 Python 환경 사용, 가장 안정적)
    try:
        result = subprocess.run(
            [sys.executable, '-m', 'hwp5.hwp5txt', str(file_path)],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=60
        )
        if result.returncode == 0:
            return [line.strip() for line in result.stdout.split('\n') if line.strip()]
        logging.warning(f"hwp5.hwp5txt 오류: {result.stderr.strip()}")
    except FileNotFoundError:
        pass

    # 2순위: hwp5txt CLI 폴백
    try:
        result = subprocess.run(
            ['hwp5txt', str(file_path)],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=60
        )
        if result.returncode == 0:
            return [line.strip() for line in result.stdout.split('\n') if line.strip()]
        logging.warning(f"hwp5txt 오류: {result.stderr.strip()}")
    except FileNotFoundError:
        pass

    raise ImportError(
        "HWP 바이너리 파일 처리를 위해 pyhwp가 필요합니다.\n"
        "설치 방법: pip install pyhwp"
    )
