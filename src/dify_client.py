"""
src/dify_client.py
==================
Dify Knowledge Base API 클라이언트 모듈.

Dify(https://dify.ai) 지식 베이스에 번역 결과(Markdown)를 업로드합니다.

주요 기능:
- 데이터셋(지식 베이스) 목록 조회
- 텍스트(Markdown)로 문서 생성/업로드
- 연결 상태 확인

Dify API 문서: https://docs.dify.ai/api-reference/knowledge-base
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

import requests

DEFAULT_DIFY_URL = "https://api.dify.ai/v1"


# ---------------------------------------------------------------------------
# 환경 변수 헬퍼
# ---------------------------------------------------------------------------

def get_dify_api_url() -> str:
    return os.getenv("DIFY_API_URL", DEFAULT_DIFY_URL).rstrip("/")


def get_dify_api_key() -> str:
    return os.getenv("DIFY_API_KEY", "").strip()


def get_dify_dataset_id() -> str:
    return os.getenv("DIFY_DATASET_ID", "").strip()


# ---------------------------------------------------------------------------
# API 클라이언트
# ---------------------------------------------------------------------------

class DifyClient:
    """Dify Knowledge Base REST API 래퍼."""

    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_DIFY_URL,
        timeout: float = 30.0,
    ):
        if not api_key:
            raise ValueError("Dify API 키가 비어 있습니다.")
        self.api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.api_key}",
        })

    # -----------------------------------------------------------------------
    # 연결 확인
    # -----------------------------------------------------------------------

    def check_connection(self) -> tuple[bool, str]:
        """
        API 키와 서버 URL이 유효한지 확인합니다.

        Returns:
            (success: bool, message: str)
        """
        try:
            resp = self.session.get(
                f"{self.base_url}/datasets",
                params={"page": 1, "limit": 1},
                timeout=self.timeout,
            )
            if resp.status_code == 200:
                return True, "연결 성공"
            elif resp.status_code == 401:
                return False, "API 키 인증 실패 (401 Unauthorized)"
            else:
                return False, f"서버 오류: {resp.status_code} — {resp.text[:200]}"
        except requests.exceptions.ConnectionError:
            return False, f"서버에 연결할 수 없습니다: {self.base_url}"
        except requests.exceptions.Timeout:
            return False, "요청 시간 초과"
        except Exception as exc:
            return False, f"오류: {exc}"

    # -----------------------------------------------------------------------
    # 데이터셋 목록 조회
    # -----------------------------------------------------------------------

    def list_datasets(
        self, page: int = 1, limit: int = 100
    ) -> list[dict]:
        """
        사용 가능한 지식 베이스(데이터셋) 목록을 반환합니다.

        Returns:
            [{"id", "name", "description", "document_count", "word_count"}, ...]
        """
        datasets: list[dict] = []
        current_page = page

        while True:
            try:
                resp = self.session.get(
                    f"{self.base_url}/datasets",
                    params={"page": current_page, "limit": limit},
                    timeout=self.timeout,
                )
                resp.raise_for_status()
                data = resp.json()
                items = data.get("data", [])
                for item in items:
                    datasets.append({
                        "id":             item["id"],
                        "name":           item.get("name", item["id"]),
                        "description":    item.get("description", ""),
                        "document_count": item.get("document_count", 0),
                        "word_count":     item.get("word_count", 0),
                    })
                if not data.get("has_more"):
                    break
                current_page += 1
            except Exception as exc:
                logging.error(f"[Dify] 데이터셋 목록 조회 실패: {exc}")
                break

        return datasets

    # -----------------------------------------------------------------------
    # 문서 업로드 (텍스트 / Markdown)
    # -----------------------------------------------------------------------

    def upload_document(
        self,
        dataset_id: str,
        name: str,
        content: str,
        indexing_technique: str = "high_quality",
    ) -> dict:
        """
        텍스트(Markdown)를 Dify 지식 베이스에 문서로 업로드합니다.

        Args:
            dataset_id: 대상 지식 베이스 ID
            name: 문서 이름 (중복 시 기존 문서 덮어쓰기 불가, 새 문서 생성)
            content: 업로드할 텍스트 내용
            indexing_technique: "high_quality" (권장) | "economy"

        Returns:
            Dify API 응답 JSON {"document": {...}, "batch": "..."}

        Raises:
            requests.HTTPError: HTTP 오류 발생 시
            ValueError: dataset_id가 비어있을 때
        """
        if not dataset_id:
            raise ValueError("데이터셋 ID가 비어 있습니다.")

        payload = {
            "name": name,
            "text": content,
            "indexing_technique": indexing_technique,
            "process_rule": {"mode": "automatic"},
        }

        resp = self.session.post(
            f"{self.base_url}/datasets/{dataset_id}/document/create-by-text",
            json=payload,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def upload_document_from_file(
        self,
        dataset_id: str,
        file_path: Path,
        indexing_technique: str = "high_quality",
    ) -> dict:
        """
        파일을 Dify 지식 베이스에 업로드합니다.

        Args:
            dataset_id: 대상 지식 베이스 ID
            file_path: 업로드할 .md / .txt 파일 경로
            indexing_technique: "high_quality" | "economy"

        Returns:
            Dify API 응답 JSON
        """
        if not dataset_id:
            raise ValueError("데이터셋 ID가 비어 있습니다.")
        if not file_path.exists():
            raise FileNotFoundError(f"파일이 없습니다: {file_path}")

        import json as _json

        data_str = _json.dumps({
            "indexing_technique": indexing_technique,
            "process_rule": {"mode": "automatic"},
        })

        with file_path.open("rb") as fobj:
            resp = self.session.post(
                f"{self.base_url}/datasets/{dataset_id}/document/create-by-file",
                files={"file": (file_path.name, fobj, "text/markdown")},
                data={"data": data_str},
                timeout=self.timeout,
            )
        resp.raise_for_status()
        return resp.json()


# ---------------------------------------------------------------------------
# 편의 함수 (app.py / api.py 에서 직접 호출)
# ---------------------------------------------------------------------------

def save_to_dify(
    content: str,
    document_name: str,
    api_key: str,
    api_url: str = DEFAULT_DIFY_URL,
    dataset_id: str = "",
    indexing_technique: str = "high_quality",
) -> tuple[bool, str]:
    """
    번역된 Markdown 텍스트를 Dify 지식 베이스에 저장합니다.

    Args:
        content: 업로드할 Markdown 텍스트
        document_name: 생성할 문서 이름
        api_key: Dify API 키
        api_url: Dify 서버 URL
        dataset_id: 대상 데이터셋 ID
        indexing_technique: "high_quality" | "economy"

    Returns:
        (success: bool, message: str)
    """
    if not api_key:
        return False, "Dify API 키가 설정되지 않았습니다."
    if not dataset_id:
        return False, "저장할 데이터셋(지식 베이스)을 선택하세요."
    if not content.strip():
        return False, "저장할 내용이 없습니다."

    try:
        client = DifyClient(api_key=api_key, base_url=api_url)
        result = client.upload_document(
            dataset_id=dataset_id,
            name=document_name,
            content=content,
            indexing_technique=indexing_technique,
        )
        doc_id = result.get("document", {}).get("id", "")
        doc_name = result.get("document", {}).get("name", document_name)
        return True, f"'{doc_name}' 저장 완료 (ID: {doc_id})"
    except requests.exceptions.HTTPError as exc:
        code = exc.response.status_code if exc.response is not None else "?"
        detail = ""
        try:
            detail = exc.response.json().get("message", "")
        except Exception:
            pass
        return False, f"Dify API 오류 ({code}): {detail or str(exc)}"
    except Exception as exc:
        logging.error(f"[Dify] 저장 실패: {exc}", exc_info=True)
        return False, f"저장 실패: {exc}"


def list_dify_datasets(
    api_key: str,
    api_url: str = DEFAULT_DIFY_URL,
    timeout: float = 10.0,
) -> tuple[list[dict], str]:
    """
    Dify 데이터셋 목록을 조회합니다.

    Returns:
        ([{"id": ..., "name": ...}], error_message)
        성공 시 error_message는 빈 문자열.
    """
    if not api_key:
        return [], "API 키가 비어 있습니다."
    try:
        client = DifyClient(api_key=api_key, base_url=api_url, timeout=timeout)
        ok, msg = client.check_connection()
        if not ok:
            return [], msg
        datasets = client.list_datasets()
        return datasets, ""
    except Exception as exc:
        return [], str(exc)
