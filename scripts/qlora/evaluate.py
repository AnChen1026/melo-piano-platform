"""讓原始模型或微調模型實際產生需求解析 JSON，存下原始輸出供評分（report.py）。

測試資料：合成 test（150 句，主題沒在訓練出現過）與人工撰寫 handwritten_test（40 句，句型也沒看過）。
生成用 greedy（temperature 0），和上線設定一致。

需在裝有 MLX 的環境執行，在專案根目錄：
    PYTHONPATH=. .scratch/qwen-lora/venv/bin/python -m scripts.qlora.evaluate --base
    PYTHONPATH=. .scratch/qwen-lora/venv/bin/python -m scripts.qlora.evaluate --adapter .scratch/qwen-lora/runs/parser-r8/best_adapter
"""

import argparse
import json
import time
from pathlib import Path

from backend.course_parser_spec import SYSTEM_PROMPT, transcript

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "evaluations/qwen_lora"
MODEL_PATH = ROOT / ".scratch/qwen-lora/model"
OUT = ROOT / "docs/ai-course-finder/training"


def cases():
    for row in (json.loads(line) for line in (DATA / "test.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()):
        yield {"id": None, "set": "synthetic_test", "input": row["messages"][1]["content"], "label": row["label"], "kind": row["kind"]}
    for row in (json.loads(line) for line in (DATA / "handwritten_test.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()):
        messages = [{"role": "user" if i % 2 == 0 else "assistant", "content": text} for i, text in enumerate(row["turns"])]
        yield {"id": row["id"], "set": "handwritten", "input": transcript(messages), "label": row["label"],
               "themes": row["themes"], "turns": row["turns"], "note": row["note"]}


def main():
    from mlx_lm import generate, load
    from mlx_lm.sample_utils import make_sampler

    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--base", action="store_true")
    group.add_argument("--adapter")
    parser.add_argument("--name", help="輸出檔名，預設 base 或 adapter")
    args = parser.parse_args()
    name = args.name or ("base" if args.base else "adapter")
    model, tokenizer = load(str(MODEL_PATH), adapter_path=None if args.base else args.adapter)
    sampler = make_sampler(temp=0.0)
    results = []
    start = time.perf_counter()
    for index, case in enumerate(cases(), start=1):
        messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": case["input"]}]
        prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True, enable_thinking=False)
        began = time.perf_counter()
        output = generate(model, tokenizer, prompt=prompt, max_tokens=160, sampler=sampler, verbose=False)
        results.append({**case, "output": output, "seconds": round(time.perf_counter() - began, 3)})
        if index % 20 == 0:
            print(f"{index} done ({time.perf_counter() - start:.0f}s)", flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"predictions_{name}.jsonl"
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in results), encoding="utf-8")
    print(f"saved {path} ({len(results)} cases, {time.perf_counter() - start:.0f}s)")


if __name__ == "__main__":
    main()
