"""
app.py
======
Docling PDF 번역기의 웹 인터페이스(Streamlit) 진입점입니다.

이 모듈은 다음 기능을 수행합니다:
1.  **UI 구성**: Streamlit을 사용하여 사이드바(설정)와 메인 영역(파일 업로드, 결과 표시)을 구성합니다.
2.  **상태 관리**: 세션 상태(Session State)를 사용하여 번역 기록, 언어 설정 등을 관리합니다.
3.  **문서 처리 요청**: `src.core.process_document`를 호출하여 문서 변환 및 번역을 실행합니다.
4.  **결과 표시**: 번역된 결과를 화면에 보여주고, 다운로드 기능을 제공합니다.
5.  **히스토리 관리**: `src.utils.load_history_from_disk`를 통해 이전 작업 기록을 불러옵니다.
"""

# [FIX] PyTorch + Streamlit 호환성 워크어라운드 (Issue #102)
# Streamlit의 파일 감시(hot-reload) 기능이 torch.classes.__path__._path를 잘못 참조하는 문제 해결
# 반드시 streamlit import 전에 실행되어야 함
import torch
torch.classes.__path__ = []

import streamlit as st
import base64
import os
import logging
from pathlib import Path
import shutil
from datetime import datetime

# src 모듈 임포트
from src.core import process_document, create_converter
from src.i18n import t, set_current_lang, get_current_lang
from src.utils import inject_images, load_history_from_disk
from src.mineru_parser import is_mineru_available
from src.translation.engines.ollama import (
    DEFAULT_OLLAMA_URL,
    get_ollama_base_url,
    list_ollama_models,
)

# 로깅 설정
logging.basicConfig(level=logging.INFO)

# Streamlit 페이지 설정 (반드시 가장 먼저 호출)
st.set_page_config(
    page_title="DocMindAI Translator",
    page_icon="🌐",
    layout="wide"
)

# 캐시된 Converter 생성 (speed_mode에 따라 분기)
# Issue #100: 속도 모드에 따라 다른 설정의 Converter 생성
@st.cache_resource
def get_converter(speed_mode: str = "balanced"):
    """
    Docling Converter 인스턴스를 캐싱하여 반환합니다.
    speed_mode에 따라 다른 설정으로 생성됩니다.
    """
    return create_converter(speed_mode=speed_mode)

def main():
    """
    메인 앱 실행 함수입니다.
    """
    # 1. 세션 상태 초기화
    if "history" not in st.session_state:
        # 앱 시작 시 디스크에서 히스토리 로드
        st.session_state.history = load_history_from_disk()

    # Ollama 서버 URL: 환경 변수 → 세션 상태 우선 순위
    if "ollama_base_url" not in st.session_state:
        st.session_state["ollama_base_url"] = get_ollama_base_url()

    # 언어 변경 콜백
    def set_lang_and_rerun():
        st.session_state["lang"] = st.session_state["lang_choice"]
        # st.rerun()은 segmented_control/radio의 on_change에서 자동 처리됨

    # 2. 사이드바: 설정 영역
    with st.sidebar:
        st.header(t("sidebar_header"))
        
        # 언어 선택 UI (Streamlit 버전에 따라 분기)
        lang_options = ["ko", "en"]
        if hasattr(st, "segmented_control"):
            st.segmented_control(
                t("language_label"),
                options=lang_options,
                format_func=lambda x: t(f"lang_option_{x}"),
                selection_mode="single",
                default=get_current_lang(),
                key="lang_choice",
                on_change=set_lang_and_rerun,
                disabled="is_processing" in st.session_state and st.session_state["is_processing"]
            )
        else:
            st.radio(
                t("language_label"),
                options=lang_options,
                format_func=lambda x: t(f"lang_option_{x}"),
                index=0 if get_current_lang() == "ko" else 1,
                horizontal=True,
                key="lang_choice",
                on_change=set_lang_and_rerun,
                disabled="is_processing" in st.session_state and st.session_state["is_processing"]
            )

        st.markdown("---")
        
        # 번역 옵션
        st.subheader(t("options_label"))
        
        source_lang = st.selectbox(t("src_label"), ["en", "fr", "de", "es", "it", "ja", "zh", "ko"], index=0)
        target_lang = st.selectbox(t("dest_label"), ["ko", "en", "fr", "de", "es", "it", "ja", "zh"], index=0)
        
        # --- Ollama 서버 설정 ---
        with st.expander("🦙 Ollama 서버 설정", expanded=False):
            _url_input = st.text_input(
                "서버 URL",
                value=st.session_state["ollama_base_url"],
                placeholder="http://localhost:11434",
                key="ollama_url_field",
                help="Ollama 서버 주소를 입력하세요. 변경 후 '연결 확인' 버튼을 누르면 모델 목록이 갱신됩니다.",
            )
            _col_btn, _col_status = st.columns([2, 1])
            with _col_btn:
                if st.button("연결 확인 / 모델 새로고침", use_container_width=True):
                    _new_url = _url_input.strip().rstrip("/") or DEFAULT_OLLAMA_URL
                    st.session_state["ollama_base_url"] = _new_url
                    st.rerun()

        # 현재 세션에서 사용할 Ollama URL
        _ollama_url = st.session_state["ollama_base_url"]

        # 내장 엔진 + Ollama 로컬 LLM 동적 조회
        base_engines = [
            "google", "deepl", "gemini", "openai",
            "qwen-0.6b", "lfm2", "lfm2-koen-mt",
            "nllb", "nllb-koen", "yanolja",
        ]
        ollama_models = list_ollama_models(base_url=_ollama_url)
        ollama_engines = [f"ollama:{m}" for m in ollama_models]
        engine_options = base_engines + ollama_engines

        engine = st.selectbox(
            t("engine_label"),
            engine_options,
            index=0,
            help=(
                f"Ollama {len(ollama_models)}개 모델 연결됨 ({_ollama_url})"
                if ollama_models
                else f"Ollama 서버 미연결 ({_ollama_url}) — `ollama serve` 실행 후 '연결 확인'을 누르세요."
            ),
        )

        # 로컬 LLM(Ollama / Qwen / LFM2 / NLLB 등)은 GPU/CPU 리소스 공유이므로 워커 1 권장
        local_llm_engines = {"qwen-0.6b", "lfm2", "lfm2-koen-mt", "nllb", "nllb-koen", "yanolja"}
        is_local_llm = engine in local_llm_engines or engine.startswith("ollama:")
        default_workers = 1 if is_local_llm else 8
        max_workers = st.number_input(
            t("workers_label"), 
            min_value=1, 
            max_value=16, 
            value=default_workers,
            help=t("workers_help")
        )
        
        # [NEW] 속도 모드 선택 (Issue #100)
        st.markdown("---")
        speed_mode_options = ["balanced", "fast"]
        speed_mode = st.radio(
            t("speed_mode_label"),
            options=speed_mode_options,
            format_func=lambda x: t(f"speed_mode_{x}"),
            index=0,  # 기본값: balanced
            horizontal=True,
            help=t("speed_mode_help"),
            disabled="is_processing" in st.session_state and st.session_state["is_processing"]
        )

        # [NEW] 파서 백엔드 선택 (MinerU 통합)
        st.markdown("---")
        st.subheader("🔬 파서 백엔드")
        _mineru_ok = is_mineru_available()
        parser_backend_opts = ["docling"]
        if _mineru_ok:
            parser_backend_opts.append("mineru")

        parser_backend = st.radio(
            "문서 파서",
            options=parser_backend_opts,
            format_func=lambda x: {
                "docling": "Docling (기본)",
                "mineru": "MinerU (고품질 PDF)",
            }[x],
            index=0,
            horizontal=True,
            help=(
                "Docling: 빠른 범용 파서\n"
                "MinerU: 다단 레이아웃·수식·OCR 특화 (PDF/이미지 전용)\n"
                + ("" if _mineru_ok else "\n⚠️ MinerU 미설치: pip install \"mineru[all]\"")
            ),
            disabled="is_processing" in st.session_state and st.session_state["is_processing"]
        )
        if not _mineru_ok:
            st.caption("⚠️ MinerU 미설치 — `pip install \"mineru[all]\"`")

        mineru_backend = "pipeline"
        if parser_backend == "mineru":
            mineru_backend = st.selectbox(
                "MinerU 엔진",
                options=["pipeline", "vlm-auto-engine", "hybrid-auto-engine"],
                format_func=lambda x: {
                    "pipeline": "Pipeline (CPU 친화적)",
                    "vlm-auto-engine": "VLM (고정확도, GPU 권장)",
                    "hybrid-auto-engine": "Hybrid (균형)",
                }[x],
                index=0,
                help="pipeline: 86% 정확도 / vlm-auto-engine: 90% 정확도 (GPU 필요)",
            )

    # 3. 메인 영역: 타이틀 및 파일 업로드
    st.title(t("app_title"))

    # CSS Hack: 파일 업로더 텍스트 커스터마이징
    # Streamlit 기본 업로더 텍스트를 숨기고, 선택된 언어에 맞는 텍스트를 표시합니다.
    st.markdown(f"""
    <style>
        /* Hide the default text */
        [data-testid="stFileUploader"] section > div > div > span {{
            display: none;
        }}
        /* Hide the ugly extension list in the uploader box */
        [data-testid="stFileUploader"] section > div:first-child > small {{
            display: none !important;
        }}
        [data-testid="stFileUploader"] section small {{
            display: none !important;
        }}
        /* Insert custom text */
        [data-testid="stFileUploader"] section > div > div::after {{
            content: "{t('uploader_text')}";
            display: block;
            text-align: center;
            margin-top: 10px;
            color: #666;
            font-size: 0.9em;
        }}
    </style>
    """, unsafe_allow_html=True)

    # 라벨 직접 렌더링 (언어 변경 시에도 업로더 리셋 방지)
    st.markdown(f"**{t('upload_label')}**")

    uploaded_files = st.file_uploader(
        label="file_uploader", # 고정 라벨 (화면엔 안 보임)
        label_visibility="collapsed",
        key="file_uploader", # 고정 Key
        type=[
            # 기존 Docling 지원
            "pdf", "docx", "pptx", "html", "htm", "png", "jpg", "jpeg",
            # 한글 문서
            "hwp", "hwpx",
            # 텍스트/마크다운
            "txt", "md", "markdown", "rst",
            # 프로그래밍 언어 (주석 번역)
            "py", "pyw", "js", "jsx", "ts", "tsx",
            "c", "h", "cpp", "hpp", "cc", "cxx", "cs",
            "java", "kt", "go", "rs", "swift",
            "sh", "bash", "zsh",
            # 설정 파일
            "json", "yaml", "yml", "toml", "xml",
            # 기타
            "log", "cfg", "ini", "env",
        ],
        accept_multiple_files=True
    )

    # 4. 번역 실행
    if uploaded_files:
        if st.button(t("translate_button"), type="primary", disabled="is_processing" in st.session_state and st.session_state["is_processing"]):
            st.session_state["is_processing"] = True
            st.rerun()

    if "is_processing" in st.session_state and st.session_state["is_processing"] and uploaded_files:
        # 강제 중단/초기화 버튼
        if st.button("🛑 " + t("stop_button")):
            st.session_state["is_processing"] = False
            st.rerun()

        # 속도 모드에 따른 Converter 생성 (Issue #100)
        converter = get_converter(speed_mode=speed_mode)
        
        # 진행 상태 표시줄
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        total_files = len(uploaded_files)
        results = []

        try:
            for i, uploaded_file in enumerate(uploaded_files):
                # 임시 파일 저장
                with open(uploaded_file.name, "wb") as f:
                    f.write(uploaded_file.getbuffer())
                
                # 진행률 콜백
                def update_progress(ratio, msg):
                    # 전체 진행률 = (현재 파일 인덱스 + 현재 파일 진행률) / 전체 파일 수
                    global_ratio = (i + ratio) / total_files
                    progress_bar.progress(min(global_ratio, 1.0))
                    status_text.text(t("status_processing").format(
                        current=i+1, total=total_files, filename=uploaded_file.name
                    ) + f" ({msg})")

                try:
                    # 핵심 처리 로직 호출
                    result = process_document(
                        file_path=uploaded_file.name,
                        converter=converter,
                        source_lang=source_lang,
                        dest_lang=target_lang,
                        engine=engine,
                        max_workers=max_workers,
                        progress_cb=update_progress,
                        ui_lang=get_current_lang(),
                        parser_backend=parser_backend,
                        mineru_backend=mineru_backend,
                    )
                    
                    if result:
                        results.append({
                            "filename": uploaded_file.name,
                            "output_dir": str(result["output_dir"]),
                            "html_path": str(result["html_path"])
                        })
                    
                    # 임시 파일 삭제
                    os.remove(uploaded_file.name)

                except Exception as e:
                    st.error(t("translate_error").format(filename=uploaded_file.name, error=str(e)))
                    logging.error(f"Processing failed for {uploaded_file.name}: {e}")
                    import traceback
                    st.error(traceback.format_exc())

            # 배치 처리 완료 결과 저장
            if results:
                st.success(t("status_all_done"))
                # 히스토리에 저장 (첫 번째 파일 기준으로 타이틀 생성)
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                first_file = uploaded_files[0].name
                batch_title = f"[{timestamp}] {first_file}"
                if len(uploaded_files) > 1:
                    batch_title += f" (+{len(uploaded_files)-1})"
                
                new_history_item = {
                    "id": batch_title,
                    "timestamp": timestamp,
                    "results": results,
                    "source_lang": source_lang,
                    "target_lang": target_lang,
                    "engine": engine
                }
                
                # 히스토리 형식 맞추기 (app.py 하단에서 사용하는 형식과 일치시켜야 함)
                # 하단 format_history_option에서는 h['results'] (리스트), h['source'], h['target'] 등을 씀
                # 여기서 insert하는 new_history_item 구조를 하단 코드와 맞춰야 함.
                # 기존 코드:
                # new_history_item = {
                #     "timestamp": display_time,
                #     "results": results,
                #     "source": source_lang,
                #     "target": target_lang,
                #     "engine": engine
                # }
                # id 필드는 하단에서 안 쓰는 것 같지만... 일단 놔둠.
                # display_time 포맷팅 로직 추가 필요.
                
                result_dir = results[0]["output_dir"]
                ts_str = result_dir.split("_")[-2] + "_" + result_dir.split("_")[-1]
                try:
                    dt = datetime.strptime(ts_str, "%Y%m%d_%H%M%S")
                    display_time = dt.strftime("%Y-%m-%d %H:%M:%S")
                except:
                    display_time = ts_str

                new_history_item = {
                    "timestamp": display_time,
                    "results": results,
                    "source": source_lang,
                    "target": target_lang,
                    "engine": engine
                }
                st.session_state.history.insert(0, new_history_item)
                st.info(t("batch_hint"))

        finally:
            st.session_state["is_processing"] = False
            st.rerun()

    st.markdown("---")

    # 5. 히스토리 및 결과 표시 영역
    if st.session_state.history:
        st.header(t("history_header"))
        
        # 히스토리 선택 옵션 포맷팅
        def format_history_option(h):
            files = [r['filename'] for r in h['results']]
            if len(files) == 1:
                file_str = files[0]
            else:
                file_str = f"{files[0]} + {len(files)-1} others"
            return f"[{h['timestamp']}] {file_str} ({h['source']}->{h['target']})"

        history_options = [format_history_option(h) for h in st.session_state.history]
        
        selected_idx = st.selectbox(
            t("history_select_label"),
            range(len(history_options)),
            format_func=lambda i: history_options[i],
            placeholder=t("history_placeholder")
        )
        
        if selected_idx is not None:
            selected_record = st.session_state.history[selected_idx]
            
            st.subheader(t("batch_result_header").format(n=len(selected_record['results'])))
            
            # 상단 컨트롤 영역 (집중 모드, 검수 모드) - 제거됨 (기본값 적용)

            
            # 각 결과 파일별 탭 생성
            tabs = st.tabs([res['filename'] for res in selected_record['results']])
            
            for i, res in enumerate(selected_record['results']):
                with tabs[i]:
                    output_dir = Path(res['output_dir'])
                    html_path = Path(res['html_path'])
                    
                    if not html_path.exists():
                        st.error(t("html_not_found"))
                        continue

                    # HTML 읽기 및 이미지 임베딩
                    with open(html_path, "r", encoding="utf-8") as f:
                        html_content = f.read()
                    
                    # 로컬 이미지를 Base64로 변환하여 HTML에 주입
                    html_content = inject_images(html_content, output_dir)

                    # 뷰 모드 설정 스크립트 주입
                    # HTML 로드 직후 실행되도록 body 끝에 스크립트 추가
                    # 검수 모드 활성화 (view-mode-inspect 클래스 추가) - 항상 적용
                    script = """
                    <script>
                        document.addEventListener('DOMContentLoaded', function() {
                            document.getElementById('content-container').classList.add('view-mode-inspect');
                            document.getElementById('btn-mode').classList.add('active');
                            document.getElementById('btn-mode').innerText = UI_STRINGS[currentUiLang].mode_read; // 버튼 텍스트는 반대로 (누르면 읽기모드)
                            updateUiText();
                        });
                    </script>
                    """
                    html_content += script

                    # 집중 모드: 1컬럼 (전체 너비)
                    st.info(t("single_tip"))
                    
                    # 뷰어 (전체 너비)
                    # st.iframe: scrolling 파라미터 없음 — iframe 기본값(auto)으로 스크롤 동작
                    _src = (
                        "data:text/html;charset=utf-8;base64,"
                        + base64.b64encode(html_content.encode("utf-8")).decode("ascii")
                    )
                    st.iframe(_src, height=900)
                    
                    # 폴더 열기 버튼
                    if st.button(t("open_folder"), key=f"open_{selected_idx}_{i}_focus"):
                        try:
                            os.startfile(output_dir)
                            st.success(t("open_folder_success").format(path=output_dir))
                        except Exception as e:
                            st.error(t("open_folder_failed").format(error=e))

if __name__ == "__main__":
    main()
