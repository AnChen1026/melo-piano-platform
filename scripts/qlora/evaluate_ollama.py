"""用 Ollama 跑匯入後的模型，產生和 evaluate.py 相同格式的預測，確認轉檔（MLX 4-bit → Ollama int4）沒有變差。

呼叫方式和網站（backend.services.ai_course_parser）一樣：OpenAI 相容 API、temperature 0、
max_tokens 160，不加 response_format。直接連本機 Ollama（11434），不經過閘道。
--json-mode 會加上 response_format json_object，用來重現 P6 發現的問題：限制解碼讓微調模型多輸出欄位。

用法（專案環境）：
    uv run python -m scripts.qlora.evaluate_ollama --model melo-qwen3-4b-ft --name ollama_ft
    uv run python -m scripts.qlora.evaluate_ollama --model melo-qwen3-4b-ft --name ollama_ft_json --json-mode
"""

import argparse
import json
import time

import httpx

from backend.course_parser_spec import SYSTEM_PROMPT
from backend.services.ai_course_parser import MAX_TOKENS
from scripts.qlora.evaluate import OUT, cases

OLLAMA = "http://127.0.0.1:11434/v1/chat/completions"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--json-mode", action="store_true")
    args = parser.parse_args()
    results = []
    start = time.perf_counter()
    for index, case in enumerate(cases(), start=1):
        began = time.perf_counter()
        response = httpx.post(
            OLLAMA,
            json={
                "model": args.model,
                "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": case["input"]}],
                "max_tokens": MAX_TOKENS,
                "temperature": 0,
                **({"response_format": {"type": "json_object"}} if args.json_mode else {}),
            },
            timeout=180,
        )
        response.raise_for_status()
        output = response.json()["choices"][0]["message"]["content"] or ""
        results.append({**case, "output": output, "seconds": round(time.perf_counter() - began, 3)})
        if index % 20 == 0:
            print(f"{index} done ({time.perf_counter() - start:.0f}s)", flush=True)
    path = OUT / f"predictions_{args.name}.jsonl"
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in results), encoding="utf-8")
    print(f"saved {path} ({len(results)} cases, {time.perf_counter() - start:.0f}s)")


if __name__ == "__main__":
    main()
