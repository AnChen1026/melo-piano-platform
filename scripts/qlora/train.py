"""QLoRA 微調千問 4B 的「需求解析」：4-bit 量化權重凍結，只訓練 LoRA。

參考 chinese-cold-joke-chatbot 的做法：
- 只計算最後助手回答（JSON）的交叉熵，prompt 和 padding 都遮罩
- MLX-LM 0.32.2 的預設 loss 右邊界多算一個 padding，這裡用半開區間 [答案起點, 真實長度)
- 只用 valid loss 選最佳權重，test 不參與選擇

和該專案不同的地方：每次評估同時算 train（固定抽 train_eval_size 筆）、valid、test 三組 loss，
三條曲線才能畫在同一張圖上觀察過擬合。test loss 只記錄、不用來選權重。

需在裝有 MLX 的環境執行（.scratch/qwen-lora/venv），在專案根目錄：
    PYTHONPATH=. .scratch/qwen-lora/venv/bin/python -m scripts.qlora.train [--smoke]
"""

import argparse
import json
import math
import platform
import random
import time
from importlib.metadata import version
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "evaluations/qwen_lora"
MODEL_PATH = ROOT / ".scratch/qwen-lora/model"
OUTPUT = ROOT / ".scratch/qwen-lora/runs"
METRICS = ROOT / "docs/ai-course-finder/training"
CONFIG = Path(__file__).with_name("config.json")


def read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def encode_sample(tokenizer, sample):
    """回傳 (整段 token, 答案起點)。確認 prompt 是整段的前綴，遮罩才不會切錯位置。"""
    messages = sample["messages"]
    options = {"tokenize": True, "return_dict": False, "enable_thinking": False}
    tokens = tokenizer.apply_chat_template(messages, add_generation_prompt=False, **options)
    prompt = tokenizer.apply_chat_template(messages[:-1], add_generation_prompt=True, **options)
    if tokens[: len(prompt)] != prompt or len(prompt) >= len(tokens):
        raise ValueError("對話模板的 prompt 與答案邊界不一致")
    return tokens, len(prompt)


class AnswerDataset:
    """MLX-LM CacheDataset 需要的介面。"""

    def __init__(self, rows, tokenizer):
        self.rows, self.tokenizer = rows, tokenizer

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, index):
        return self.rows[index]

    def process(self, row):
        return encode_sample(self.tokenizer, row)


def answer_mask(positions, lengths):
    """target 位置在 [答案起點, 真實長度)；不能把第一個 padding 算成答案。"""
    return (positions >= lengths[:, 0:1]) & (positions < lengths[:, 1:2])


def answer_loss(model, batch, lengths):
    import mlx.core as mx
    from mlx import nn

    logits = model(batch[:, :-1])
    targets = batch[:, 1:]
    positions = mx.arange(1, batch.shape[1])[None, :]
    mask = answer_mask(positions, lengths)
    n_tokens = mask.sum()
    loss = nn.losses.cross_entropy(logits, targets).astype(mx.float32)
    return (loss * mask).sum() / n_tokens, n_tokens


class ExperimentLog:
    """每次回報記下 train loss；每 steps_per_eval 步算 train 子集／valid／test 三組 loss，用 valid 選權重。"""

    def __init__(self, model, sets, config, best_dir, metrics_file):
        from mlx.utils import tree_flatten  # noqa: F401

        self.model, self.sets, self.config = model, sets, config
        self.best_dir, self.metrics_file = best_dir, metrics_file
        self.rows, self.best_loss, self.best_step = [], float("inf"), None

    def evaluate_all(self):
        from mlx_lm.tuner.trainer import evaluate

        out = {}
        for name, dataset in self.sets.items():
            value = float(evaluate(self.model, dataset, batch_size=self.config["eval_batch_size"], num_batches=-1,
                                   max_seq_length=self.config["max_seq_length"], loss=answer_loss))
            if not math.isfinite(value):
                raise RuntimeError(f"{name} loss 非有限值，停止訓練")
            out[name] = value
        return out

    def on_train_loss_report(self, info):
        import mlx.core as mx
        from mlx.utils import tree_flatten

        if not math.isfinite(info["train_loss"]):
            raise RuntimeError("訓練 loss 非有限值，停止訓練")
        step = info["iteration"]
        self.rows.append({"kind": "train_report", "step": step, "train_loss": info["train_loss"],
                          "tokens_per_second": info.get("tokens_per_second"), "peak_memory_gb": info.get("peak_memory")})
        print(f"step={step} train_loss={info['train_loss']:.4f} tok/s={info.get('tokens_per_second', 0):.0f}", flush=True)
        if step % self.config["steps_per_eval"] == 0:
            losses = self.evaluate_all()
            self.rows.append({"kind": "eval", "step": step, **losses})
            print(f"step={step} eval " + " ".join(f"{k}={v:.4f}" for k, v in losses.items()), flush=True)
            if losses["valid"] < self.best_loss:
                self.best_loss, self.best_step = losses["valid"], step
                weights = dict(tree_flatten(self.model.trainable_parameters()))
                mx.save_safetensors(str(self.best_dir / "adapters.safetensors"), weights)
                write_json(self.best_dir / "selection.json", {"step": step, **losses})
            write_json(self.metrics_file, self.rows)

    def on_val_loss_report(self, info):
        pass


def main():
    import mlx.core as mx
    import mlx.optimizers as optim
    import numpy as np
    from mlx_lm import load
    from mlx_lm.tuner.datasets import CacheDataset
    from mlx_lm.tuner.trainer import TrainingArgs, train
    from mlx_lm.tuner.utils import linear_to_lora_layers, print_trainable_parameters

    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true", help="只跑幾步量速度，輸出到獨立資料夾")
    args = parser.parse_args()
    config = json.loads(CONFIG.read_text())
    name = "smoke" if args.smoke else config["run_name"]
    if args.smoke:
        config.update(iters=6, steps_per_report=2, steps_per_eval=6)
    run_dir = OUTPUT / name
    best_dir = run_dir / "best_adapter"
    if (best_dir / "adapters.safetensors").exists() and not args.smoke:
        raise SystemExit(f"{best_dir} 已有權重，請先改名備份再重新訓練")
    best_dir.mkdir(parents=True, exist_ok=True)
    random.seed(config["seed"])
    np.random.seed(config["seed"])
    mx.random.seed(config["seed"])

    model, tokenizer = load(str(MODEL_PATH))
    rows = {split: read_jsonl(DATA / f"{split}.jsonl") for split in ("train", "valid", "test")}
    train_subset = random.Random(config["seed"]).sample(rows["train"], config["train_eval_size"])
    datasets = {}
    lengths = {}
    for split, data in (("train", rows["train"]), ("train_eval", train_subset), ("valid", rows["valid"]), ("test", rows["test"])):
        dataset = CacheDataset(AnswerDataset(data, tokenizer))
        sizes = [len(dataset[i][0]) for i in range(len(dataset))]
        if max(sizes) > config["max_seq_length"]:
            raise ValueError(f"{split} 有樣本超過 max_seq_length（{max(sizes)}），答案會被截斷")
        datasets[split] = dataset
        lengths[split] = {"max_tokens": max(sizes), "mean_tokens": sum(sizes) / len(sizes), "rows": len(sizes)}
    print("tokens:", json.dumps(lengths), flush=True)

    eval_sets = {"train": datasets["train_eval"], "valid": datasets["valid"], "test": datasets["test"]}
    logger = ExperimentLog(model, eval_sets, config, best_dir, METRICS / f"{name}_metrics.json")
    start = time.perf_counter()
    base = logger.evaluate_all()
    logger.rows.append({"kind": "eval", "step": 0, **base})
    print("base " + " ".join(f"{k}={v:.4f}" for k, v in base.items()), f"({time.perf_counter() - start:.0f}s)", flush=True)

    model.freeze()
    linear_to_lora_layers(model, config["num_layers"], config["lora_parameters"])
    print_trainable_parameters(model)
    adapter_config = {"fine_tune_type": "lora", "num_layers": config["num_layers"], "lora_parameters": config["lora_parameters"]}
    write_json(best_dir / "adapter_config.json", adapter_config)
    training_args = TrainingArgs(
        batch_size=config["batch_size"], iters=config["iters"], steps_per_report=config["steps_per_report"],
        steps_per_eval=config["iters"] + 1, steps_per_save=config["iters"] + 1,
        max_seq_length=config["max_seq_length"], grad_checkpoint=True,
        adapter_file=str(run_dir / "last_adapters.safetensors"),
    )
    train_start = time.perf_counter()
    train(model, optim.Adam(learning_rate=config["learning_rate"]), datasets["train"],
          args=training_args, training_callback=logger, loss=answer_loss)
    elapsed = time.perf_counter() - train_start
    trainable = sum(v.size for _, v in __import__("mlx.utils", fromlist=["tree_flatten"]).tree_flatten(model.trainable_parameters()))
    total = sum(v.size for _, v in __import__("mlx.utils", fromlist=["tree_flatten"]).tree_flatten(model.parameters()))
    summary = {
        "run": name, "config": config, "model": str(MODEL_PATH.relative_to(ROOT)),
        "model_manifest": json.loads((MODEL_PATH / "download-manifest.json").read_text())["repo"]
        if (MODEL_PATH / "download-manifest.json").exists() else None,
        "python": platform.python_version(), "versions": {p: version(p) for p in ("mlx", "mlx-lm", "transformers", "numpy")},
        "train_seconds": elapsed, "peak_memory_gb": mx.get_peak_memory() / 1e9,
        "trainable_parameters": int(trainable), "total_parameters": int(total),
        "base_losses": base, "best_step": logger.best_step, "best_valid_loss": logger.best_loss,
        "token_lengths": lengths,
        "data_summary": json.loads((DATA / "data_summary.json").read_text()),
    }
    write_json(METRICS / f"{name}_summary.json", summary)
    print(f"完成：最佳 step={logger.best_step} valid={logger.best_loss:.4f}，訓練 {elapsed:.0f} 秒", flush=True)


if __name__ == "__main__":
    main()
