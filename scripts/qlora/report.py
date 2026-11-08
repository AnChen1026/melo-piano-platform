"""QLoRA 結果：評分、比較三種做法、畫圖。在專案環境執行（不需要 MLX）。

比較：
- 規則解析：原本的 parse_criteria（線上正在用的做法）
- 原始千問 4B：同一份系統提示詞，沒有微調
- 微調千問 4B：最佳 adapter

用法（--retrieval 需要閘道與 bge-m3，會用 search_query 實際檢索）：
    uv run python -m scripts.qlora.report --run parser-r8 [--retrieval]
"""

import argparse
import json
import math
from pathlib import Path

from backend.course_parser_spec import CRITERIA_FIELDS, InvalidParse, parse_output

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs/ai-course-finder/training"
METHODS = {"rules": "規則解析（原本）", "base": "原始千問 4B", "adapter": "微調千問 4B"}
COLORS = {"rules": "#9aa3ad", "base": "#e0a23a", "adapter": "#2f6fde"}


def read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def user_turns(case):
    if case.get("turns"):
        return [t for i, t in enumerate(case["turns"]) if i % 2 == 0]
    return [line[3:] for line in case["input"].splitlines() if line.startswith("學生：")]


def rules_parse(case):
    """原本線上的做法：每句學生的話用 parse_criteria 解析，後面蓋過前面；其他樂器規則判斷無關。"""
    from backend.services.course_chat import SHORT_CITY
    from backend.services.recommendation import _unsupported, parse_criteria

    criteria = {}
    for text in user_turns(case):
        criteria.update(parse_criteria(SHORT_CITY.sub(r"\1市", text)))
    last = user_turns(case)[-1]
    return {
        "intent": "off_topic" if _unsupported(last) else "course_search",
        **{field: criteria.get(field) for field in CRITERIA_FIELDS},
        "search_query": "\n".join(user_turns(case)[-3:]),
    }


def score(cases, predictions):
    """predictions[i] 是 dict（解析成功）或 None（格式不合）。"""
    n = len(cases)
    out = {"n": n, "valid_json": sum(p is not None for p in predictions) / n}
    out["intent"] = sum(p is not None and p["intent"] == c["label"]["intent"] for c, p in zip(cases, predictions)) / n
    for field in CRITERIA_FIELDS:
        out[field] = sum(p is not None and p[field] == c["label"][field] for c, p in zip(cases, predictions)) / n
    out["criteria_all"] = sum(
        p is not None and all(p[f] == c["label"][f] for f in CRITERIA_FIELDS) for c, p in zip(cases, predictions)
    ) / n
    out["all_fields"] = sum(
        p is not None and p["intent"] == c["label"]["intent"] and all(p[f] == c["label"][f] for f in CRITERIA_FIELDS)
        for c, p in zip(cases, predictions)
    ) / n
    return out


def query_exact(cases, predictions):
    """合成 test 的 search_query 有標準答案，比對是否完全相同（忽略空白）。"""
    def norm(s):
        return "".join((s or "").split()).lower()

    hits = [p is not None and norm(p["search_query"]) == norm(c["label"].get("search_query")) for c, p in zip(cases, predictions)]
    return sum(hits) / len(hits)


def parsed_predictions(rows):
    result = []
    for row in rows:
        try:
            result.append(parse_output(row["output"]))
        except InvalidParse:
            result.append(None)
    return result


def retrieval_recall(cases, predictions, k=3):
    """用 search_query 做向量檢索，前 k 名有沒有預期主題。模型沒給主題（空字串或格式錯）時，退回合併最近三句。"""
    from backend.core.database import SessionLocal
    from backend.services.ai_semantic import embed_texts
    from backend.services.rag_retrieval import published_course_scores
    from scripts.evaluate_rag_retrieval import catalog_truth

    truth = catalog_truth()
    pairs = [(c, p) for c, p in zip(cases, predictions) if c.get("themes")]
    queries = [(p["search_query"] if p and p["search_query"] else "\n".join(user_turns(c)[-3:])) for c, p in pairs]
    vectors = []
    for start in range(0, len(queries), 8):
        batch = embed_texts(queries[start : start + 8])
        if batch is None:
            raise SystemExit("embedding_gateway_unavailable")
        vectors.extend(batch)
    hits = []
    with SessionLocal() as db:
        for (case, _), vector in zip(pairs, vectors):
            scores = published_course_scores(db, vector)
            top = sorted(scores, key=lambda course_id: -scores[course_id])[:k]
            hits.append(any(truth.get(course_id, {}).get("theme") in case["themes"] for course_id in top))
    return {"n": len(hits), f"recall@{k}": sum(hits) / len(hits)}


def plot_losses(metrics, summary):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams["font.sans-serif"] = ["PingFang TC", "Heiti TC", "Microsoft JhengHei", "Arial Unicode MS", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    reports = [r for r in metrics if r["kind"] == "train_report"]
    evals = [r for r in metrics if r["kind"] == "eval"]
    best = summary["best_step"]

    fig, ax = plt.subplots(figsize=(10, 5.2))
    ax.plot([r["step"] for r in reports], [r["train_loss"] for r in reports], color="#9aa3ad", linewidth=1,
            label="train（每 10 步的批次平均）")
    for name, color, label in (("train", "#555", "train（固定 100 筆）"), ("valid", "#2f6fde", "valid（選權重用）"),
                               ("test", "#e0623a", "test（只記錄，不參與選擇）")):
        ax.plot([r["step"] for r in evals], [r[name] for r in evals], marker="o", markersize=4, color=color, label=label)
    ax.axvline(best, color="#2f6fde", linestyle="--", linewidth=1)
    ax.annotate(f"最佳 step {best}", (best, ax.get_ylim()[1] * 0.9), xytext=(6, 0), textcoords="offset points", color="#2f6fde")
    ax.set_yscale("log")
    ax.set_xlabel("訓練步數（step）")
    ax.set_ylabel("loss（只算 JSON 答案，對數刻度）")
    ax.set_title("QLoRA 需求解析：train／valid／test loss")
    ax.grid(alpha=0.3, which="both")
    ax.legend()
    fig.tight_layout()
    fig.savefig(OUT / "loss_curves.png", dpi=160)
    plt.close(fig)

    trained = [r for r in evals if r["step"] > 0]
    fig, ax = plt.subplots(figsize=(10, 4.5))
    ax.plot([r["step"] for r in trained], [r["valid"] - r["train"] for r in trained], marker="o", color="#2f6fde",
            label="valid − train")
    ax.plot([r["step"] for r in trained], [r["test"] - r["train"] for r in trained], marker="o", color="#e0623a",
            label="test − train")
    ax.axhline(0, color="black", linewidth=0.8)
    ax.axvline(best, color="#2f6fde", linestyle="--", linewidth=1)
    ax.set_xlabel("訓練步數（step）")
    ax.set_ylabel("loss 差距")
    ax.set_title("過擬合觀察：沒看過的資料和訓練資料的 loss 差距")
    ax.grid(alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(OUT / "overfitting_gap.png", dpi=160)
    plt.close(fig)

    base = evals[0]
    best_row = next(r for r in evals if r["step"] == best)
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
    for ax, metric, title in ((axes[0], lambda v: v, "loss"), (axes[1], math.exp, "perplexity（困惑度）")):
        names = ["train", "valid", "test"]
        x = range(len(names))
        b = axes[0].bar if False else ax.bar
        bars1 = b([i - 0.2 for i in x], [metric(base[n]) for n in names], 0.4, label="原始模型", color="#e0a23a")
        bars2 = b([i + 0.2 for i in x], [metric(best_row[n]) for n in names], 0.4, label=f"微調（step {best}）", color="#2f6fde")
        ax.bar_label(bars1, fmt="%.3f" if title == "loss" else "%.2f", fontsize=8)
        ax.bar_label(bars2, fmt="%.3f" if title == "loss" else "%.2f", fontsize=8)
        ax.set_xticks(list(x), names)
        ax.set_title(title)
        ax.legend()
    fig.suptitle("微調前後的 loss 與困惑度")
    fig.tight_layout()
    fig.savefig(OUT / "base_vs_adapter.png", dpi=160)
    plt.close(fig)


def plot_accuracy(results):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    metrics = [("valid_json", "JSON 合格"), ("intent", "意圖"), ("level", "程度"), ("delivery_mode", "上課方式"),
               ("region", "地區"), ("max_price", "預算"), ("time_slot", "時段"), ("all_fields", "全部正確")]
    fig, axes = plt.subplots(2, 1, figsize=(12, 8))
    for ax, dataset, title in ((axes[0], "synthetic_test", "合成 test（主題沒在訓練出現過）"),
                               (axes[1], "handwritten", "人工撰寫 test（句型也沒看過）")):
        width = 0.27
        for offset, method in zip((-width, 0, width), METHODS):
            values = [results[method][dataset][key] for key, _ in metrics]
            bars = ax.bar([i + offset for i in range(len(metrics))], values, width, label=METHODS[method], color=COLORS[method])
            ax.bar_label(bars, labels=[f"{v:.0%}" for v in values], fontsize=7)
        ax.set_xticks(range(len(metrics)), [label for _, label in metrics])
        ax.set_ylim(0, 1.12)
        n = results["adapter"][dataset]["n"]
        ax.set_title(f"{title}，{n} 句")
        ax.legend(loc="lower right", fontsize=8)
    fig.tight_layout()
    fig.savefig(OUT / "task_accuracy.png", dpi=160)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", default="parser-r8")
    parser.add_argument("--retrieval", action="store_true")
    args = parser.parse_args()
    metrics = json.loads((OUT / f"{args.run}_metrics.json").read_text())
    summary = json.loads((OUT / f"{args.run}_summary.json").read_text())
    plot_losses(metrics, summary)

    rows = {name: read_jsonl(OUT / f"predictions_{name}.jsonl") for name in ("base", "adapter")}
    cases = rows["adapter"]
    preds = {name: parsed_predictions(rows[name]) for name in rows}
    preds["rules"] = [rules_parse(case) for case in cases]
    results = {}
    for method in METHODS:
        results[method] = {}
        for dataset in ("synthetic_test", "handwritten"):
            idx = [i for i, c in enumerate(cases) if c["set"] == dataset]
            subset = [cases[i] for i in idx]
            predicted = [preds[method][i] for i in idx]
            results[method][dataset] = score(subset, predicted)
            if dataset == "synthetic_test" and method != "rules":
                results[method][dataset]["search_query_exact"] = query_exact(subset, predicted)
            if dataset == "handwritten" and args.retrieval:
                results[method][dataset]["retrieval"] = retrieval_recall(subset, predicted)
        if method in rows:
            seconds = [r["seconds"] for r in rows[method]]
            results[method]["seconds_median"] = sorted(seconds)[len(seconds) // 2]
    plot_accuracy(results)
    errors = []
    for i, case in enumerate(cases):
        if case["set"] != "handwritten":
            continue
        entry = {"id": case["id"], "turns": case["turns"], "note": case["note"], "label": case["label"]}
        for method in METHODS:
            p = preds[method][i]
            entry[method] = p if p is not None else {"invalid_output": rows[method][i]["output"][:200] if method in rows else None}
        errors.append(entry)
    (OUT / "task_results.json").write_text(
        json.dumps({"results": results, "handwritten_cases": errors}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    print(json.dumps(results, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
