"""
src/translation/__init__.py
===========================
번역 엔진 패키지의 초기화 모듈입니다.

이 모듈은 다음 기능을 수행합니다:
1.  **팩토리 함수 제공**: 엔진 이름(문자열)을 입력받아 해당 번역 엔진 인스턴스를 생성하는 `create_translator` 함수를 제공합니다.
2.  **엔진 등록**: 지원되는 번역 엔진 클래스들을 매핑하여 관리합니다.
"""

from .base import BaseTranslator
from .engines.google import GoogleTranslator
from .engines.deepl import DeepLTranslator
from .engines.gemini import GeminiTranslator
from .engines.openai import OpenAITranslator
from .engines.qwen import QwenTranslator
from .engines.lfm2 import LFM2Translator
from .engines.lfm2_koen import LFM2KOENTranslator
from .engines.nllb import NLLBTranslator
from .engines.nllb_koen import NLLBKOENTranslator
from .engines.yanolja import YanoljaTranslator
from .engines.ollama import OllamaTranslator

def create_translator(engine_name: str) -> BaseTranslator:
    """
    지정된 이름의 번역 엔진 인스턴스를 생성하여 반환합니다.

    Args:
        engine_name (str): 번역 엔진 이름.
            - 내장 엔진: 'google', 'deepl', 'gemini', 'openai', 'qwen-0.6b',
                        'lfm2', 'lfm2-koen-mt', 'nllb', 'nllb-koen', 'yanolja'
            - Ollama: 'ollama:<모델명>'  (예: 'ollama:llama3.2', 'ollama:qwen2.5:7b')

    Returns:
        BaseTranslator: 생성된 번역 엔진 인스턴스

    Raises:
        ValueError: 지원하지 않는 엔진 이름일 경우 발생
    """
    name = engine_name.strip()

    # Ollama: "ollama:<model>" 또는 "ollama:<model>@<base_url>" 형태
    #   예) ollama:llama3.2
    #       ollama:qwen2.5:7b@http://192.168.1.10:11434
    # 모델명에 콜론이 포함될 수 있으므로 '@' 로만 URL 구분
    if name.lower().startswith("ollama:"):
        rest = name[len("ollama"):]          # ":model" 또는 ":model@url"
        if "@http" in rest:
            # 마지막 @http 위치 기준으로 분리 (URL 내 콜론 허용)
            at_idx = rest.rfind("@http")
            model = rest[1:at_idx].strip()   # 첫 ':' 제거
            base_url: Optional[str] = rest[at_idx + 1:].strip()
        else:
            model = rest[1:].strip()
            base_url = None
        return OllamaTranslator(model=model, base_url=base_url)

    engines = {
        "google": GoogleTranslator,
        "deepl": DeepLTranslator,
        "gemini": GeminiTranslator,
        "openai": OpenAITranslator,
        "qwen": QwenTranslator,
        "qwen-0.6b": QwenTranslator,
        "lfm2": LFM2Translator,
        "lfm2-koen-mt": LFM2KOENTranslator,
        "nllb": NLLBTranslator,
        "nllb-koen": NLLBKOENTranslator,
        "yanolja": YanoljaTranslator,
    }

    engine_class = engines.get(name.lower())
    if not engine_class:
        raise ValueError(f"Unsupported engine: {engine_name}")

    return engine_class()
