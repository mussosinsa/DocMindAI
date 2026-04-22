"""
src/i18n.py
===========
애플리케이션의 국제화(Internationalization)를 담당하는 모듈입니다.

이 모듈은 다음 기능을 수행합니다:
1.  **번역 데이터 관리**: 한국어(ko)와 영어(en) UI 문자열 딕셔너리를 관리합니다.
2.  **언어 설정**: 세션 상태를 통해 현재 UI 언어를 설정하고 가져옵니다.
3.  **번역 함수**: 키(Key)를 입력받아 현재 언어에 맞는 문자열을 반환하는 `t()` 함수를 제공합니다.
"""

import streamlit as st

# ==== i18n: 화면에 보이는 문자열 번역 딕셔너리 및 헬퍼 ====
# 키(Key) 구조: {언어코드: {식별자: 번역문}}
TRANSLATIONS = {
    "en": {
        # 언어 선택 라벨
        "lang_option_ko": "Korean",
        "lang_option_en": "English",
        "language_label": "Language",

        # 업로더 텍스트 (CSS Hack용)
        "uploader_text": "Drag and drop files here",
        "uploader_limit": "Docs: PDF, DOCX, PPTX | Code: .py, .js, .ts, .java, .c, .go | Text: .md, .txt, .json",

        # 타이틀 / 사이드바
        "app_title": "DocMindAI Translator",
        "sidebar_header": "Settings",
        "upload_label": "Upload files (Documents, Code, Text)",
        "options_label": "Translation options",
        "src_label": "Source language",
        "dest_label": "Target language",
        "engine_label": "Translation engine",
        "workers_label": "Number of parallel workers",
        "workers_help": "Higher means faster but uses more system resources. Recommended: 8",
        "speed_mode_label": "Speed mode",
        "speed_mode_fast": "⚡ Fast",
        "speed_mode_balanced": "⚖️ Balanced",
        "speed_mode_help": "Fast: Faster processing, slightly lower quality. Balanced: Best quality (default).",
        "translate_button": "Start new translation",
        "stop_button": "Stop current translation",
        "history_header": "Translation history",
        "history_select_label": "Select previous result",
        "history_placeholder": "Select a record...",

        # 진행 상태 / 배치 결과
        "status_processing": "[{current}/{total}] Processing: {filename}...",
        "status_all_done": "All tasks have been completed!",
        "batch_success": "Successfully translated {n} file(s)!",
        "batch_hint": "👇 You can check the results for each file below.",
        "batch_result_header": "📦 Batch translation results ({n} file(s))",

        # 번역 중 에러
        "translate_error": "An error occurred while processing {filename}: {error}",

        # 히스토리 관련
        "history_missing_files": "Could not find result files in the selected record.",
        "history_load_failed": "Failed to load history: {error}",

        # 탭 / 공통 다운로드 설명
        "tab_interactive": "Interactive view",
        "tab_download": "Download",
        "download_desc": "You can download the translated results or open the folder.",

        # HTML / 폴더 관련
        "html_not_found": "Could not find the HTML file.",
        "open_folder": "📂 Open result folder",
        "open_folder_primary": "📂 Open result folder",
        "open_folder_failed": "Failed to open the folder: {error}",
        "open_folder_success": "Opened folder: {path}",
        "download_folder_hint": "Files are stored on the server at: {path}",


        # 단일 결과 영역
        "single_tip": "💡 Tip: Use the buttons at the top right of the result page to switch view modes (side-by-side / expanded).",
        "focus_mode_label": "🔍 Focus Mode",
        "focus_mode_help": "Hide sidebar & controls for a wider view.",
        "view_mode_label": "👁️ Inspection Mode",
        "view_mode_help": "Show source and translation side-by-side.",
        "download_options_label": "💾 Downloads",

        # 다운로드 버튼 라벨
        "zip_download": "📦 Download ZIP",
        "html_download": "🌐 Download HTML",
        "md_download": "📝 Download Markdown (.md)",
        "zip_download_all": "📦 Download all results (ZIP)",
        "html_download_interactive": "🌐 Download interactive HTML",

        # Dify 지식 베이스
        "dify_section_label": "🧠 Dify Knowledge Base",
        "dify_api_url_label": "Dify API URL",
        "dify_api_key_label": "API Key",
        "dify_api_key_help": "Dify → Settings → API Keys",
        "dify_connect_button": "🔗 Connect & Load Datasets",
        "dify_refresh_help": "Refresh dataset list",
        "dify_connecting": "Connecting...",
        "dify_connected": "✅ Connected",
        "dify_connect_failed": "❌ Connection failed: {error}",
        "dify_dataset_label": "Select knowledge base",
        "dify_dataset_placeholder": "Select a dataset",
        "dify_no_datasets": "No datasets found. Create one in Dify first.",
        "dify_auto_save_label": "Auto-save after translation",
        "dify_save_button": "💾 Save to Dify",
        "dify_saving": "Saving to Dify...",
        "dify_save_success": "✅ {message}",
        "dify_save_failed": "❌ Save failed: {error}",
        "dify_not_configured": "Configure Dify settings in the sidebar first.",
        "dify_no_content": "No translated content to save.",
        "dify_doc_name_label": "Document name",
        "dify_indexing_label": "Indexing quality",
        "dify_indexing_high": "High quality (slower, better search)",
        "dify_indexing_economy": "Economy (faster, basic search)",
    },
    "ko": {
        # 언어 선택 라벨
        "lang_option_ko": "한국어",
        "lang_option_en": "영어",
        "language_label": "언어 (Language)",

        # 업로더 텍스트 (CSS Hack용)
        "uploader_text": "파일을 이곳에 드래그 앤 드롭하세요",
        "uploader_limit": "문서: PDF, DOCX, PPTX | 코드: .py, .js, .ts, .java, .c, .go | 텍스트: .md, .txt, .json",

        # 타이틀 / 사이드바
        "app_title": "DocMindAI 번역기",
        "sidebar_header": "설정",
        "upload_label": "파일 업로드 (문서, 코드, 텍스트)",
        "options_label": "번역 옵션",
        "src_label": "원본 언어 (Source)",
        "dest_label": "대상 언어 (Target)",
        "engine_label": "번역 엔진",
        "workers_label": "병렬 처리 워커 수 (Workers)",
        "workers_help": "높을수록 빠르지만 시스템 리소스를 많이 사용합니다. 권장: 8",
        "speed_mode_label": "속도 모드",
        "speed_mode_fast": "⚡ 빠른 모드",
        "speed_mode_balanced": "⚖️ 균형 모드",
        "speed_mode_help": "빠른 모드: 처리 속도 우선, 품질 약간 하락. 균형 모드: 최고 품질 (기본값).",
        "translate_button": "새로 번역 시작",
        "stop_button": "진행 중인 번역 중지",
        "history_header": "번역 기록",
        "history_select_label": "이전 번역 결과 선택",
        "history_placeholder": "기록을 선택하세요...",

        # 진행 상태 / 배치 결과
        "status_processing": "[{current}/{total}] 처리 중: {filename}...",
        "status_all_done": "모든 작업이 완료되었습니다!",
        "batch_success": "총 {n}개의 파일 번역이 완료되었습니다!",
        "batch_hint": "👇 아래에서 각 파일의 결과를 확인할 수 있습니다.",
        "batch_result_header": "📦 배치 번역 결과 ({n}개 파일)",

        # 번역 중 에러
        "translate_error": "오류가 발생했습니다 ({filename}): {error}",

        # 히스토리 관련
        "history_missing_files": "선택한 기록에서 결과 파일을 찾을 수 없습니다.",
        "history_load_failed": "기록 불러오기 실패: {error}",

        # 탭 / 공통 다운로드 설명
        "tab_interactive": "인터랙티브 뷰",
        "tab_download": "다운로드",
        "download_desc": "번역된 결과물들을 다운로드하거나 폴더를 열어 확인할 수 있습니다.",

        # HTML / 폴더 관련
        "html_not_found": "HTML 파일을 찾을 수 없습니다.",
        "open_folder": "📂 결과 폴더 열기",
        "open_folder_primary": "📂 결과 폴더 열기",
        "open_folder_failed": "폴더를 열 수 없습니다: {error}",
        "open_folder_success": "폴더를 열었습니다: {path}",
        "download_folder_hint": "서버에 저장된 결과 경로: {path}",


        # 단일 결과 영역
        "single_tip": "💡 **팁:** 결과물 페이지 우측 상단의 버튼을 눌러 뷰 모드(좌우 병렬 / 펼치기)를 변경할 수 있습니다.",
        "focus_mode_label": "🔍 집중 모드",
        "focus_mode_help": "사이드바와 컨트롤을 숨기고 화면을 넓게 사용합니다.",
        "view_mode_label": "👁️ 검수 모드",
        "view_mode_help": "원문과 번역문을 좌우로 나란히 비교합니다.",
        "download_options_label": "💾 다운로드",

        # 다운로드 버튼 라벨
        "zip_download": "📦 ZIP 다운로드",
        "html_download": "🌐 HTML 다운로드",
        "md_download": "📝 Markdown(.md) 다운로드",
        "zip_download_all": "📦 전체 결과 다운로드 (ZIP)",
        "html_download_interactive": "🌐 인터랙티브 HTML 다운로드",

        # Dify 지식 베이스
        "dify_section_label": "🧠 Dify 지식 베이스",
        "dify_api_url_label": "Dify API URL",
        "dify_api_key_label": "API Key",
        "dify_api_key_help": "Dify → 설정 → API 키",
        "dify_connect_button": "🔗 연결 확인 및 목록 불러오기",
        "dify_refresh_help": "지식 베이스 목록 새로고침",
        "dify_connecting": "연결 중...",
        "dify_connected": "✅ 연결됨",
        "dify_connect_failed": "❌ 연결 실패: {error}",
        "dify_dataset_label": "지식 베이스 선택",
        "dify_dataset_placeholder": "데이터셋을 선택하세요",
        "dify_no_datasets": "지식 베이스가 없습니다. Dify에서 먼저 생성하세요.",
        "dify_auto_save_label": "번역 완료 후 자동 저장",
        "dify_save_button": "💾 Dify에 저장",
        "dify_saving": "Dify에 저장 중...",
        "dify_save_success": "✅ {message}",
        "dify_save_failed": "❌ 저장 실패: {error}",
        "dify_not_configured": "사이드바에서 Dify 설정을 먼저 입력하세요.",
        "dify_no_content": "저장할 번역 내용이 없습니다.",
        "dify_doc_name_label": "문서 이름",
        "dify_indexing_label": "인덱싱 품질",
        "dify_indexing_high": "고품질 (느리지만 정확한 검색)",
        "dify_indexing_economy": "이코노미 (빠르지만 기본 검색)",
    },
}


def get_current_lang() -> str:
    """
    현재 세션에 설정된 UI 언어 코드(en/ko)를 반환합니다.
    기본값은 'ko'입니다.
    """
    if "lang" not in st.session_state:
        st.session_state["lang"] = "ko"  # 기본: 한국어
    return st.session_state["lang"]


def set_current_lang(lang_code: str) -> None:
    """
    UI 언어 코드를 세션에 저장합니다.
    """
    st.session_state["lang"] = lang_code


def t(key: str) -> str:
    """
    현재 언어 설정에 맞는 번역 문자열을 반환합니다.
    해당 언어에 키가 없으면 영어(en)를, 영어에도 없으면 키 자체를 반환합니다.
    
    Args:
        key (str): 번역 키 식별자
        
    Returns:
        str: 번역된 문자열
    """
    lang = get_current_lang()
    return TRANSLATIONS.get(lang, {}).get(
        key,
        TRANSLATIONS.get("en", {}).get(key, key),
    )
