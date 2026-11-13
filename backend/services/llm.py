"""呼叫大型語言模型寫一段文字，可以用 .env 切換 Gemini、OpenAI，或 Ollie 電腦上的本機模型（千問等，經過 Ollama 閘道）。

沒有金鑰、逾時、服務忙碌時回傳 None，並在後端紀錄寫下原因，由呼叫端改用規則產生的文字。
每次呼叫最多等 LLM_TIMEOUT_SECONDS 秒；逾時或服務忙碌會再試一次。

.env 設定：
  LLM_PROVIDER=gemini              全站預設用哪家，沒寫就是 gemini（也可以寫 openai 或 local）
  PRACTICE_FEEDBACK_LLM_PROVIDER=  只換某個功能，例如練習回饋改用 openai，課前摘要不受影響
  QUIZ_GENERATION_LLM_PROVIDER=    AI 出題用哪家；沒寫就用 openai（Gemini 常回 503 忙碌）
  GEMINI_API_KEY、GEMINI_MODEL
  OPENAI_API_KEY、OPENAI_MODEL
  local：AI_COURSE_GATEWAY_URL、AI_COURSE_GATEWAY_TOKEN（和 AI 找課共用同一個閘道），LOCAL_MODEL 不寫就是千問 qwen3:4b
  <功能>_LLM_MODEL=                只換某個功能用的模型，例如 PRACTICE_FEEDBACK_LLM_MODEL=qwen3:14b
  LLM_TIMEOUT_SECONDS=20
"""

import logging
import time
from urllib.parse import urlsplit

import httpx

from backend.core.config import read_env_value

logger = logging.getLogger(__name__)

# 功能名稱：用在 <功能>_LLM_PROVIDER 設定
FEATURE_PRACTICE_FEEDBACK = "practice_feedback"
FEATURE_LESSON_SUMMARY = "lesson_summary"
FEATURE_QUIZ_GENERATION = "quiz_generation"

DEFAULT_PROVIDER = "gemini"
# 有些功能自己的預設，不跟全站的 LLM_PROVIDER：AI 出題一次要回很多題，Gemini 忙碌時常失敗，預設用 OpenAI
FEATURE_DEFAULT_PROVIDERS = {FEATURE_QUIZ_GENERATION: "openai"}
DEFAULT_MODELS = {"gemini": "gemini-3.8-flash", "openai": "gpt-4o-mini", "local": "qwen3:4b-instruct-2507-q4_K_M"}
KEY_NAMES = {"gemini": "GEMINI_API_KEY", "openai": "OPENAI_API_KEY", "local": "AI_COURSE_GATEWAY_TOKEN"}
# 本機閘道一次最多回 1400 個 token（scripts/local_ai_gateway.py），送出時不能超過
LOCAL_MAX_TOKENS = 1400
DEFAULT_MODEL = DEFAULT_MODELS["gemini"]

DEFAULT_TIMEOUT_SECONDS = 20.0
MAX_ATTEMPTS = 2
RETRY_WAIT_SECONDS = 2

OPENAI_URL = "https://api.openai.com/v1/chat/completions"
# 錯誤訊息裡有這些字，代表是暫時的問題（逾時、忙碌、額度用完），可以再試一次
RETRYABLE_MARKERS = ("429", "500", "502", "503", "504", "DEADLINE", "UNAVAILABLE", "RESOURCE_EXHAUSTED", "timed out", "high demand")


class LLMError(Exception):
    def __init__(self, message: str, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


def generate_text(system_instruction: str, content: str, feature: str | None = None, temperature: float = 0.3) -> str | None:
    """只要文字；失敗時回傳 None（原因已寫進後端紀錄）。"""
    text, _reason = generate_text_with_reason(system_instruction, content, feature, temperature)
    return text


def generate_text_with_reason(
    system_instruction: str,
    content: str,
    feature: str | None = None,
    temperature: float = 0.3,
    timeout_seconds: float | None = None,
) -> tuple[str | None, str | None]:
    """回傳 (文字, 失敗原因)。成功時失敗原因是 None。timeout_seconds 給比較久的工作（例如一次出很多題）用，不給就照 .env。"""
    provider = provider_for(feature)
    call = PROVIDERS.get(provider)
    if call is None:
        return _fail(f"不認得 LLM 供應商「{provider}」，請在 .env 寫 gemini、openai 或 local。")
    api_key = read_env_value(KEY_NAMES[provider])
    if api_key is None:
        return None, f"沒有設定 {KEY_NAMES[provider]}。"
    model = model_for(feature, provider)
    timeout = max(_timeout_seconds(), timeout_seconds or 0)

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            text = (call(api_key, model, system_instruction, content, timeout, temperature) or "").strip()
        except LLMError as error:
            reason = f"{provider}（{model}）：{error}"
            if error.retryable and attempt < MAX_ATTEMPTS:
                logger.warning("LLM 暫時失敗，%s 秒後重試：%s", RETRY_WAIT_SECONDS, reason)
                time.sleep(RETRY_WAIT_SECONDS)
                continue
            return _fail(reason)
        if text:
            return text, None
        return _fail(f"{provider}（{model}）有回應，但沒有文字內容。")
    return _fail(f"{provider}（{model}）一直沒有成功。")


def model_for(feature: str | None, provider: str) -> str:
    """先看這個功能自己指定的模型（<功能>_LLM_MODEL），再看這家的模型設定，最後用預設。"""
    chosen = read_env_value(f"{feature.upper()}_LLM_MODEL") if feature else None
    return (chosen or read_env_value(f"{provider.upper()}_MODEL") or DEFAULT_MODELS[provider]).strip()


def provider_for(feature: str | None) -> str:
    """先看這個功能自己的設定，再看這個功能的預設（FEATURE_DEFAULT_PROVIDERS），最後才是全站預設。"""
    chosen = read_env_value(f"{feature.upper()}_LLM_PROVIDER") if feature else None
    chosen = chosen or FEATURE_DEFAULT_PROVIDERS.get(feature or "")
    return (chosen or read_env_value("LLM_PROVIDER") or DEFAULT_PROVIDER).strip().lower()


def _timeout_seconds() -> float:
    try:
        return max(1.0, float(read_env_value("LLM_TIMEOUT_SECONDS") or DEFAULT_TIMEOUT_SECONDS))
    except ValueError:
        return DEFAULT_TIMEOUT_SECONDS


def _fail(reason: str) -> tuple[None, str]:
    logger.error("呼叫 LLM 失敗：%s", reason)
    return None, reason


def _is_retryable(message: str) -> bool:
    return any(marker in message for marker in RETRYABLE_MARKERS)


def _call_gemini(api_key, model, system_instruction, content, timeout, temperature) -> str | None:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=int(timeout * 1000)))
    try:
        response = client.models.generate_content(
            model=model,
            contents=content,
            config=types.GenerateContentConfig(system_instruction=system_instruction, temperature=temperature),
        )
    except httpx.TimeoutException as error:
        raise LLMError(f"等了 {timeout:g} 秒沒有回應", retryable=True) from error
    except Exception as error:
        message = str(error)[:300]
        raise LLMError(message, retryable=_is_retryable(message)) from error
    return response.text


def _call_openai(api_key, model, system_instruction, content, timeout, temperature) -> str | None:
    try:
        response = httpx.post(
            OPENAI_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "temperature": temperature,
                "messages": [
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": content},
                ],
            },
            timeout=timeout,
        )
    except httpx.TimeoutException as error:
        raise LLMError(f"等了 {timeout:g} 秒沒有回應", retryable=True) from error
    except httpx.HTTPError as error:
        raise LLMError(f"連線失敗：{error}", retryable=True) from error
    if response.status_code != 200:
        try:
            detail = response.json().get("error", {}).get("message", "")
        except ValueError:
            detail = response.text[:200]
        retryable = response.status_code == 429 or response.status_code >= 500
        raise LLMError(f"{response.status_code} {detail}".strip(), retryable=retryable)
    choices = response.json().get("choices") or []
    return choices[0]["message"]["content"] if choices else None


def _gateway_url() -> str | None:
    """本機閘道的網址：只接受 https，或本機自己的 http（和 AI 找課的檢查一樣）。
    host.docker.internal 是 Docker 容器裡指「這台電腦」的名字：後端跑在 Docker、閘道跑在電腦上時用。"""
    url = (read_env_value("AI_COURSE_GATEWAY_URL") or "").rstrip("/")
    parts = urlsplit(url)
    if not url or not parts.hostname or parts.username or parts.query or parts.fragment:
        return None
    if parts.scheme == "https" or (parts.scheme == "http" and parts.hostname in {"127.0.0.1", "localhost", "::1", "host.docker.internal"}):
        return url
    return None


def _call_local(api_key, model, system_instruction, content, timeout, temperature) -> str | None:
    """Ollie 電腦上的 Ollama（千問等），經過 scripts/local_ai_gateway.py。閘道同時只處理一個請求，忙碌時回 503。"""
    url = _gateway_url()
    if url is None:
        raise LLMError("沒有設定 AI_COURSE_GATEWAY_URL，或網址不是 https。")
    try:
        response = httpx.post(
            url + "/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "temperature": max(0.0, min(1.0, temperature)),
                "max_tokens": LOCAL_MAX_TOKENS,
                # 千問 3.5 這類「會先思考」的模型，思考會把 1400 token 用光、正文變成空的；關掉思考直接回答
                # "reasoning_effort": "none",
                "messages": [
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": content},
                ],
            },
            timeout=timeout,
        )
    except httpx.TimeoutException as error:
        raise LLMError(f"等了 {timeout:g} 秒沒有回應", retryable=True) from error
    except httpx.HTTPError as error:
        raise LLMError(f"連不到本機模型閘道：{error.__class__.__name__}", retryable=True) from error
    if response.status_code != 200:
        detail = {
            401: "閘道金鑰不對",
            413: "送出的內容太長",
            422: f"閘道不接受這個請求（模型 {model} 可能沒有開放，或內容太長）",
            429: "閘道每分鐘次數用完",
            503: "本機模型忙碌中或沒有開",
        }.get(response.status_code, "")
        raise LLMError(f"{response.status_code} {detail}".strip(), retryable=response.status_code in (429, 503))
    choices = response.json().get("choices") or []
    return choices[0]["message"]["content"] if choices else None


PROVIDERS = {"gemini": _call_gemini, "openai": _call_openai, "local": _call_local}
