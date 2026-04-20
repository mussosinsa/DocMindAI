"""
src/mineru_parser.py
====================
MinerU를 사용하여 문서를 파싱하고 구조화된 텍스트를 추출하는 모듈.

MinerU는 IBM Docling보다 향상된 PDF 레이아웃 분석을 제공합니다:
- 다단(Multi-column) 레이아웃 올바른 읽기 순서 복원
- 수식을 LaTeX로 자동 변환
- 표를 HTML로 추출
- 스캔 PDF OCR 지원 (109개 언어)
- 머리글/바닥글/페이지 번호 자동 제거

MinerU 설치: pip install "mineru[all]"
"""

import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import Optional


def is_mineru_available() -> bool:
    """MinerU가 설치되어 있는지 확인합니다."""
    try:
        import mineru  # noqa: F401
        return True
    except ImportError:
        return False


def parse_with_mineru(
    file_path: str,
    output_dir: str,
    backend: str = "pipeline",
    parse_method: str = "auto",
    formula_enable: bool = True,
    table_enable: bool = True,
) -> tuple[str, Optional[list]]:
    """
    MinerU로 문서를 파싱하여 Markdown 내용과 구조화된 블록 목록을 반환합니다.

    Args:
        file_path: 입력 파일 경로 (PDF, 이미지 등)
        output_dir: MinerU 출력 저장 디렉토리
        backend: 파싱 엔진
            - "pipeline"          : CPU 친화적, 표준 정확도 (~86%)
            - "vlm-auto-engine"   : VLM 기반, 고정확도 (~90%), GPU 권장
            - "hybrid-auto-engine": 하이브리드, 균형 잡힌 성능
        parse_method: 파싱 전략 ("auto" | "txt" | "ocr")
        formula_enable: 수식 LaTeX 변환 여부
        table_enable: 표 구조 추출 여부

    Returns:
        (markdown_content, content_blocks)
        - markdown_content: 변환된 Markdown 문자열
        - content_blocks: _content_list.json 의 para_blocks 리스트 (없으면 None)

    Raises:
        ImportError: MinerU가 설치되지 않은 경우
        RuntimeError: 파싱 실패 시
    """
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    # Python API 시도 → CLI 폴백
    try:
        _parse_via_python_api(
            file_path, out_path, backend, parse_method,
            formula_enable, table_enable
        )
    except (ImportError, ModuleNotFoundError):
        raise ImportError(
            "MinerU가 설치되지 않았습니다.\n"
            "설치 방법: pip install \"mineru[all]\""
        )
    except Exception as api_err:
        logging.warning(f"[MinerU] Python API 실패 ({api_err}), CLI 폴백 시도...")
        _parse_via_cli(file_path, out_path, backend, parse_method)

    # 출력 파일 탐색
    stem = Path(file_path).stem
    markdown_content = _read_markdown_output(out_path, stem)
    content_blocks = _read_content_list(out_path, stem)

    return markdown_content, content_blocks


def _parse_via_python_api(
    file_path: str,
    output_dir: Path,
    backend: str,
    parse_method: str,
    formula_enable: bool,
    table_enable: bool,
) -> None:
    """mineru Python API로 문서를 파싱합니다."""
    # mineru.cli.common.do_parse 시도 (v1.x+)
    try:
        from mineru.cli.common import do_parse
        do_parse(
            input_path=str(file_path),
            output_dir=str(output_dir),
            backend=backend,
            parse_method=parse_method,
            formula_enable=formula_enable,
            table_enable=table_enable,
        )
        return
    except (ImportError, TypeError):
        pass

    # mineru.do_parse 시도
    try:
        from mineru import do_parse  # type: ignore
        fname = Path(file_path).name
        with open(file_path, 'rb') as f:
            data = f.read()
        do_parse(
            output_dir=str(output_dir),
            pdf_file_names=[fname],
            input_data=[data],
            parse_method=parse_method,
            backend=backend,
        )
        return
    except (ImportError, TypeError):
        pass

    raise RuntimeError("mineru Python API를 찾을 수 없습니다.")


def _parse_via_cli(
    file_path: str,
    output_dir: Path,
    backend: str,
    parse_method: str,
) -> None:
    """mineru CLI로 문서를 파싱합니다."""
    base_cmd = [
        'mineru',
        '-p', str(file_path),
        '-o', str(output_dir),
        '-b', backend,
        '-m', parse_method,
    ]

    for cmd in [base_cmd, [sys.executable, '-m', 'mineru.cli'] + base_cmd[1:]]:
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=600,
            )
            if result.returncode == 0:
                return
            logging.warning(f"[MinerU CLI] 오류: {result.stderr.strip()[:200]}")
        except FileNotFoundError:
            continue

    raise RuntimeError(
        "MinerU CLI를 실행할 수 없습니다.\n"
        "설치 확인: pip install \"mineru[all]\""
    )


def _read_markdown_output(output_dir: Path, stem: str) -> str:
    """MinerU가 생성한 Markdown 파일을 찾아 반환합니다."""
    # 가능한 경로 순서대로 시도
    candidates = [
        output_dir / f"{stem}.md",
        output_dir / stem / f"{stem}.md",
    ]
    for path in candidates:
        if path.exists():
            return path.read_text(encoding='utf-8')

    # 재귀 탐색
    for md_file in sorted(output_dir.rglob("*.md")):
        return md_file.read_text(encoding='utf-8')

    raise FileNotFoundError(
        f"MinerU Markdown 출력 파일을 찾을 수 없습니다: {output_dir}"
    )


def _read_content_list(output_dir: Path, stem: str) -> Optional[list]:
    """MinerU의 _content_list.json을 읽어 para_blocks를 반환합니다."""
    candidates = [
        output_dir / f"{stem}_content_list.json",
        output_dir / stem / f"{stem}_content_list.json",
    ]
    for path in candidates:
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding='utf-8'))
                # {"para_blocks": [...]} 또는 직접 리스트 형태 모두 지원
                if isinstance(data, dict):
                    return data.get("para_blocks") or data.get("content_list")
                if isinstance(data, list):
                    return data
            except json.JSONDecodeError as e:
                logging.warning(f"[MinerU] content_list.json 파싱 오류: {e}")

    # 재귀 탐색
    for json_file in sorted(output_dir.rglob("*_content_list.json")):
        try:
            data = json.loads(json_file.read_text(encoding='utf-8'))
            if isinstance(data, dict):
                return data.get("para_blocks") or data.get("content_list")
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass

    return None


def get_images_dir(output_dir: str, stem: str) -> Optional[Path]:
    """MinerU 추출 이미지 디렉토리를 반환합니다."""
    out = Path(output_dir)
    for candidate in [out / "images", out / stem / "images"]:
        if candidate.is_dir():
            return candidate
    return None
