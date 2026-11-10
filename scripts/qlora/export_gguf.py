"""把最佳 adapter 變成跨平台的 GGUF 模型，準備上傳 Hugging Face 給組員下載。

export_ollama.py 做出的是 Ollama MLX 格式（只有 Apple Silicon Mac 能跑）；這支做的是 GGUF Q4_K_M，
Windows／Linux／Mac 的 Ollama 都能跑。組員用 `ollama pull hf.co/Ollie12304/melo-qwen3-4b-ft` 下載。

1. mlx_lm fuse --dequantize：adapter 合併回千問 4B（用 MLX 環境，約 7.5 GB）
2. 修正 tokenizer 設定：transformers 5 存的 extra_special_tokens 是 list，llama.cpp 用的 transformers 4 讀不了
3. llama.cpp convert_hf_to_gguf.py → f16 GGUF（約 7.5 GB）
4. llama-quantize → Q4_K_M（約 2.5 GB）。這版 Ollama 不能在匯入時量化 GGUF，也不再支援 ADAPTER
5. 匯入本機 Ollama 並寫好上傳資料夾：GGUF、template（官方千問 instruct 的 Go 模板）、params、README
6. 刪除中間檔

只有發布新版的人要做，需要（都放在 .scratch，不進 Git）：
- .scratch/qwen-lora/venv：MLX 訓練環境
- .scratch/llama.cpp：git clone https://github.com/ggml-org/llama.cpp
- .scratch/gguf-venv：uv venv --python 3.12 .scratch/gguf-venv
    uv pip install --python .scratch/gguf-venv/bin/python -r .scratch/llama.cpp/requirements/requirements-convert_hf_to_gguf.txt cmake
- llama-quantize：在 .scratch/llama.cpp 執行
    ../gguf-venv/bin/cmake -B build -DLLAMA_CURL=OFF -DGGML_METAL=OFF && ../gguf-venv/bin/cmake --build build --target llama-quantize -j 8

在專案根目錄：
    .scratch/gguf-venv/bin/python -m scripts.qlora.export_gguf --run parser-r8
完成後先用 evaluate_ollama.py 驗收本機的 melo-qwen3-4b-ft-gguf，再照印出的指令上傳。
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRATCH = ROOT / ".scratch"
BASE = SCRATCH / "qwen-lora"
LLAMA_CPP = SCRATCH / "llama.cpp"
UPLOAD = SCRATCH / "hf-upload"
MODEL_CARD = ROOT / "docs/ai-course-finder/huggingface-model-card.md"
BASE_OLLAMA_MODEL = "qwen3:4b-instruct-2507-q4_K_M"
HF_REPO = "Ollie12304/melo-qwen3-4b-ft"
GGUF_NAME = "melo-qwen3-4b-ft-Q4_K_M.gguf"


def run(command, **kwargs):
    print("$", " ".join(str(c) for c in command), flush=True)
    return subprocess.run(command, check=True, **kwargs)


def fix_tokenizer_config(model_dir: Path):
    path = model_dir / "tokenizer_config.json"
    config = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(config.get("extra_special_tokens"), list):
        config["additional_special_tokens"] = config.pop("extra_special_tokens")
        path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


def base_template_and_params():
    """官方千問 instruct 的 Go 模板與參數。HF 自動產生的模板是思考版，回覆前會多一段 </think>。"""
    modelfile = run(["ollama", "show", "--modelfile", BASE_OLLAMA_MODEL], capture_output=True, text=True).stdout
    template = re.search(r'TEMPLATE """(.*?)"""', modelfile, re.S).group(1)
    params: dict = {}
    for line in modelfile.splitlines():
        if not line.startswith("PARAMETER "):
            continue
        _, key, value = line.split(maxsplit=2)
        value = value.strip().strip('"')
        if key == "stop":
            params.setdefault("stop", []).append(value)
        else:
            number = float(value)
            params[key] = int(number) if number.is_integer() and key != "temperature" else number
    body = [line for line in modelfile.splitlines() if not line.startswith(("FROM", "#"))]
    return template, params, body


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", default="parser-r8")
    parser.add_argument("--name", default="melo-qwen3-4b-ft-gguf", help="匯入本機 Ollama 的名字，驗收用")
    parser.add_argument("--keep-intermediate", action="store_true")
    args = parser.parse_args()

    adapter = BASE / "runs" / args.run / "best_adapter"
    mlx_python = BASE / "venv/bin/python"
    quantize = LLAMA_CPP / "build/bin/llama-quantize"
    for path, hint in [
        (adapter / "adapters.safetensors", "請先訓練"),
        (mlx_python, "需要 MLX 訓練環境"),
        (LLAMA_CPP / "convert_hf_to_gguf.py", "請先 clone llama.cpp"),
        (quantize, "請先編譯 llama-quantize"),
    ]:
        if not path.exists():
            raise SystemExit(f"找不到 {path}：{hint}（見檔案開頭說明）")

    fused = BASE / f"fused-{args.run}"
    f16 = BASE / f"{args.run}-f16.gguf"
    q4 = BASE / f"{args.run}-Q4_K_M.gguf"
    if fused.exists():
        shutil.rmtree(fused)
    run([mlx_python, "-m", "mlx_lm", "fuse", "--model", BASE / "model", "--adapter-path", adapter,
         "--save-path", fused, "--dequantize"])
    fix_tokenizer_config(fused)
    run([sys.executable, LLAMA_CPP / "convert_hf_to_gguf.py", fused, "--outtype", "f16", "--outfile", f16])
    run([quantize, f16, q4, "Q4_K_M"])

    template, params, body = base_template_and_params()
    modelfile = BASE / f"Modelfile-{args.run}-gguf"
    modelfile.write_text(f"FROM {q4}\n" + "\n".join(body) + "\n", encoding="utf-8")
    run(["ollama", "create", args.name, "-f", modelfile])

    if UPLOAD.exists():
        shutil.rmtree(UPLOAD)
    UPLOAD.mkdir()
    os.link(q4, UPLOAD / GGUF_NAME)
    (UPLOAD / "template").write_text(template, encoding="utf-8")
    (UPLOAD / "params").write_text(json.dumps(params, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    shutil.copy(MODEL_CARD, UPLOAD / "README.md")

    if not args.keep_intermediate:
        shutil.rmtree(fused)
        f16.unlink()

    print(f"""
完成：本機 Ollama 模型 {args.name}，上傳資料夾 {UPLOAD}
1. 驗收：uv run python -m scripts.qlora.evaluate_ollama --model {args.name} --name ollama_ft_gguf
2. 更新 {MODEL_CARD.relative_to(ROOT)} 的評估數字後，重跑本程式或手動複製到上傳資料夾
3. 上傳（會公開）：.scratch/gguf-venv/bin/hf upload {HF_REPO} {UPLOAD} . --commit-message "<版本說明>"
4. 組員更新：ollama pull hf.co/{HF_REPO} 後再 ollama cp 成 melo-qwen3-4b-ft""")


if __name__ == "__main__":
    main()
