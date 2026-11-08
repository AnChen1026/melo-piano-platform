"""AI 找課的需求解析：用微調過的千問把對話整理成條件與檢索主題。

設定 COURSE_PARSER_LLM_MODEL（例如 melo-qwen3-4b-ft）才啟用，模型要先在閘道的 AI_GATEWAY_CHAT_MODELS 開放。
沒設定、閘道沒開、輸出不合規格時回傳 None，呼叫端改用原本的規則解析（parse_criteria），網站照常能用。
提示詞與輸出規格在 backend/course_parser_spec.py，和訓練用的是同一份。
"""

import logging
import os

import httpx

from backend.course_parser_spec import (
    SYSTEM_PROMPT,
    InvalidParse,
    parse_output,
    transcript,
)
from backend.services.llm import _gateway_url, read_env_value

logger = logging.getLogger(__name__)
TIMEOUT_SECONDS = 30
MAX_TOKENS = 160


def parser_model() -> str:
    return (read_env_value("COURSE_PARSER_LLM_MODEL") or "").strip()


def parse_conversation(messages: list[dict]) -> dict | None:
    """messages 的 role 是 user 或 assistant，最後一則是學生剛說的話。"""
    model = parser_model()
    url = _gateway_url()
    token = read_env_value("AI_COURSE_GATEWAY_TOKEN") or os.environ.get("AI_COURSE_GATEWAY_TOKEN", "")
    if not model or not url or not token:
        return None
    try:
        response = httpx.post(
            url + "/v1/chat/completions",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": transcript(messages)},
                ],
                "max_tokens": MAX_TOKENS,
                "temperature": 0,
                # 不加 response_format：Ollama 的 JSON 限制解碼會擋掉模型學到的第一個 token「{"」，
                # 微調模型因此偏離訓練分布、多輸出欄位（P6 實測合格率 0%）。格式由 parse_output 檢查。
            },
            timeout=TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return parse_output(response.json()["choices"][0]["message"]["content"])
    except (httpx.HTTPError, KeyError, IndexError, ValueError, InvalidParse) as error:
        logger.warning("需求解析改用規則：%s", type(error).__name__)
        return None
