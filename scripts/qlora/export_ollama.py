"""把最佳 adapter 變成 Ollama 模型（P0 驗證過的路線）。

1. mlx_lm fuse --dequantize：adapter 合併回千問 4B，並解除量化（約 7.5 GB）
2. Modelfile 沿用線上千問的對話模板與參數
3. ollama create -q int4：匯入並量化（約 3.4 GB）。這版 Ollama 從 safetensors 匯入不支援 Q4_K_M
4. 刪除中間檔

需在裝有 MLX 的環境執行，在專案根目錄：
    PYTHONPATH=. .scratch/qwen-lora/venv/bin/python -m scripts.qlora.export_ollama --run parser-r8

訓練用 MLX 4-bit、上線用 Ollama int4，量化方式不同，匯入後要用 evaluate_ollama.py 重新驗收。

注意：做出來的模型用 Ollama 的 MLX 引擎，只有 Apple Silicon Mac 能跑。要發布給組員（Windows 也能跑）用 export_gguf.py。
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / ".scratch/qwen-lora"
BASE_OLLAMA_MODEL = "qwen3:4b-instruct-2507-q4_K_M"


def run(command, **kwargs):
    print("$", " ".join(str(c) for c in command), flush=True)
    return subprocess.run(command, check=True, **kwargs)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", default="parser-r8")
    parser.add_argument("--name", default="melo-qwen3-4b-ft")
    parser.add_argument("--keep-fused", action="store_true")
    args = parser.parse_args()
    adapter = BASE / "runs" / args.run / "best_adapter"
    if not (adapter / "adapters.safetensors").exists():
        raise SystemExit(f"找不到 {adapter}/adapters.safetensors，請先訓練")
    fused = BASE / f"fused-{args.run}"
    if fused.exists():
        shutil.rmtree(fused)
    run([sys.executable, "-m", "mlx_lm", "fuse", "--model", str(BASE / "model"), "--adapter-path", str(adapter),
         "--save-path", str(fused), "--dequantize"])
    modelfile = run(["ollama", "show", "--modelfile", BASE_OLLAMA_MODEL], capture_output=True, text=True).stdout
    lines = [line for line in modelfile.splitlines() if not line.startswith(("FROM", "#"))]
    (fused / "Modelfile").write_text("FROM .\n" + "\n".join(lines) + "\n", encoding="utf-8")
    run(["ollama", "create", args.name, "-q", "int4", "-f", str(fused / "Modelfile")], cwd=fused)
    if not args.keep_fused:
        shutil.rmtree(fused)
    run(["ollama", "show", args.name])
    print(f"完成：Ollama 模型 {args.name}。閘道要在 AI_GATEWAY_CHAT_MODELS 開放這個名字。")


if __name__ == "__main__":
    main()
