"""AI 找課檢索驗收：Recall@k、MRR、門檻校準、多輪查詢改寫、上課方式篩選。

用法（閘道與 bge-m3 要開著，資料庫要有示範課程與 pgvector 索引）：

    AI_COURSE_GATEWAY_URL=http://127.0.0.1:18763 AI_COURSE_GATEWAY_TOKEN=… \\
    AI_COURSE_EMBEDDING_VERSION=… uv run python -m scripts.evaluate_rag_retrieval

查詢集：evaluations/rag/queries.jsonl，每句標註「正確答案是哪幾個課程主題」。
切分：依主題分組，70% 主題當 dev（拿來決定門檻與 k）、30% 當 test（最後只報數字），同一主題不跨組。
輸出：docs/ai-course-finder/retrieval/ 的 metrics.json、report.md 與圖。
"""

import json
import random
import statistics
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QUERIES = ROOT / "evaluations/rag/queries.jsonl"
CATALOG = ROOT / "scripts/data/aicourse-demo.json"
OUT = ROOT / "docs/ai-course-finder/retrieval"
SEED = 42
DEV_RATIO = 0.7
KS = list(range(1, 11))
STRATEGIES = ["last", "recent", "follow_up"]


def split_queries(rows):
    themes = sorted({row["themes"][0] for row in rows if row["type"] == "topic"})
    random.Random(SEED).shuffle(themes)
    dev_themes = set(themes[: round(len(themes) * DEV_RATIO)])
    for index, row in enumerate(rows):
        if row["type"] == "topic":
            row["split"] = "dev" if row["themes"][0] in dev_themes else "test"
        else:
            # 其他類型數量少，依序輪流分配，兩組都有
            row["split"] = "dev" if index % 2 == 0 else "test"
    return rows


def catalog_truth():
    from scripts.import_demo_data import identity

    source = json.loads(CATALOG.read_text(encoding="utf-8"))
    return {
        identity("course", course["id"]): {
            "theme": course["curriculum_key"],
            "delivery": course["delivery_mode"],  # online／onsite／hybrid（真實資料，不是資料庫存的值）
            "price": course["price_amount"],
        }
        for course in source["courses"]
    }


def truly_satisfies(info, criteria):
    mode = criteria.get("delivery_mode")
    if mode == "online" and info["delivery"] not in ("online", "hybrid"):
        return False
    if mode == "in_person" and info["delivery"] not in ("onsite", "hybrid"):
        return False
    return not (criteria.get("max_price") is not None and info["price"] > criteria["max_price"])


def relevant_ids(row, truth):
    return {
        course_id
        for course_id, info in truth.items()
        if info["theme"] in row["themes"] and truly_satisfies(info, row["criteria"])
    }


def rank(scores):
    return [course_id for course_id, _ in sorted(scores.items(), key=lambda kv: -kv[1])]


def first_hit(ranking, relevant):
    for position, course_id in enumerate(ranking, start=1):
        if course_id in relevant:
            return position
    return None


def summarize(results, ks=KS):
    if not results:
        return {}
    out = {"n": len(results)}
    for k in ks:
        out[f"hit@{k}"] = sum(1 for r in results if r["first_hit"] and r["first_hit"] <= k) / len(results)
    out["mrr"] = sum(1 / r["first_hit"] for r in results if r["first_hit"]) / len(results)
    out["precision@3"] = statistics.mean(r["precision@3"] for r in results)
    return out


def evaluate_one(ranking, relevant):
    top3 = ranking[:3]
    return {
        "first_hit": first_hit(ranking, relevant),
        "precision@3": sum(1 for course_id in top3 if course_id in relevant) / 3,
    }


def choose_threshold(in_scope, out_scope):
    """在 dev 上找讓「該回答的有回答」和「該拒答的有拒答」平均最高的門檻；同分取較低（少拒答）。"""
    candidates = sorted({round(x, 3) for x in in_scope + out_scope})
    best = None
    for tau in candidates:
        keep = sum(1 for x in in_scope if x >= tau) / len(in_scope)
        reject = sum(1 for x in out_scope if x < tau) / len(out_scope)
        score = (keep + reject) / 2
        if best is None or score > best[0] + 1e-12:
            best = (score, tau, keep, reject)
    return {"tau": best[1], "balanced_accuracy": best[0], "keep_rate": best[2], "reject_rate": best[3]}


def conservative_threshold(in_scope, out_scope, min_keep=0.98):
    """寧可放行也不要誤擋：保留率至少 min_keep 的門檻裡，取最高的那個。"""
    best = None
    for tau in sorted({round(x, 3) for x in in_scope + out_scope}):
        rates = gate_rates(in_scope, out_scope, tau)
        if rates["keep_rate"] >= min_keep:
            best = {"tau": tau, "min_keep": min_keep, **rates}
    return best


def gate_rates(in_scope, out_scope, tau):
    return {
        "keep_rate": sum(1 for x in in_scope if x >= tau) / len(in_scope),
        "reject_rate": sum(1 for x in out_scope if x < tau) / len(out_scope),
    }


def plots(data, threshold):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams["font.sans-serif"] = ["PingFang TC", "Heiti TC", "Microsoft JhengHei", "Arial Unicode MS", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    OUT.mkdir(parents=True, exist_ok=True)
    tau = threshold["tau"]

    # 1. 分數分布
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5))
    bins = [x / 100 for x in range(30, 96, 2)]
    axes[0].hist(data["dev_in_top1"], bins=bins, alpha=0.65, label=f"該有結果的查詢（{len(data['dev_in_top1'])} 句）", color="#2f6fde")
    axes[0].hist(data["dev_out_top1"], bins=bins, alpha=0.75, label=f"不該有結果的查詢（{len(data['dev_out_top1'])} 句）", color="#e0623a")
    conservative = data["threshold"]["conservative"]["tau"]
    axes[0].axvline(conservative, color="#2f6fde", linestyle="--", label=f"採用：保守門檻 τ = {conservative:.3f}")
    axes[0].axvline(tau, color="black", linestyle=":", label=f"平均最高 τ = {tau:.3f}")
    axes[0].set_title("每句查詢的最高相似度（dev）")
    axes[0].set_xlabel("最相似課程的餘弦相似度")
    axes[0].set_ylabel("查詢數")
    axes[0].legend()
    axes[1].hist(data["dev_irrelevant_scores"], bins=bins, density=True, alpha=0.55, label="不相關的課", color="#9aa3ad")
    axes[1].hist(data["dev_relevant_scores"], bins=bins, density=True, alpha=0.65, label="相關的課（正確主題）", color="#2f6fde")
    axes[1].set_title("查詢和每門課的相似度（dev，主題查詢）")
    axes[1].set_xlabel("餘弦相似度")
    axes[1].set_ylabel("比例（密度）")
    axes[1].legend()
    fig.tight_layout()
    fig.savefig(OUT / "score_distribution.png", dpi=160)
    plt.close(fig)

    # 2. 門檻掃描
    taus = [x / 1000 for x in range(300, 901, 5)]
    keep = [gate_rates(data["dev_in_top1"], data["dev_out_top1"], t)["keep_rate"] for t in taus]
    reject = [gate_rates(data["dev_in_top1"], data["dev_out_top1"], t)["reject_rate"] for t in taus]
    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.plot(taus, keep, label="該有結果的查詢：保留率", color="#2f6fde")
    ax.plot(taus, reject, label="不該有結果的查詢：拒答率", color="#e0623a")
    ax.plot(taus, [(a + b) / 2 for a, b in zip(keep, reject)], label="兩者平均", color="black", linewidth=1)
    ax.axvline(tau, color="black", linestyle="--", label=f"平均最高 τ = {tau:.3f}")
    ax.axvline(data["threshold"]["conservative"]["tau"], color="#2f6fde", linestyle="--", label=f"保守門檻 τ = {data['threshold']['conservative']['tau']:.3f}（保留率 ≥ 98%）")
    ax.axvline(0.83, color="#888", linestyle=":", label="健康新聞專案的 0.83")
    ax.set_xlabel("門檻 τ")
    ax.set_ylabel("比例")
    ax.set_title("門檻對保留率與拒答率的影響（dev）")
    ax.legend(loc="lower left")
    fig.tight_layout()
    fig.savefig(OUT / "threshold_sweep.png", dpi=160)
    plt.close(fig)

    # 3. Hit@k
    fig, ax = plt.subplots(figsize=(8, 4.5))
    for split, color in (("dev", "#2f6fde"), ("test", "#e0623a")):
        summary = data["topic"][split]
        ax.plot(KS, [summary[f"hit@{k}"] for k in KS], marker="o", label=f"{split}（{summary['n']} 句）", color=color)
    ax.set_xticks(KS)
    ax.set_ylim(0, 1.02)
    ax.set_xlabel("k（取前幾門課）")
    ax.set_ylabel("Recall@k（前 k 名至少有一門正確）")
    ax.set_title("單句主題查詢的 Recall@k")
    ax.grid(alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(OUT / "recall_at_k.png", dpi=160)
    plt.close(fig)

    # 4. 多輪查詢改寫與上課方式篩選
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5))
    names = {"last": "只看最後一句", "recent": "最近三句全接", "follow_up": "像追問才接上一句"}
    width = 0.38
    positions = range(len(STRATEGIES))
    for offset, group, label, color in ((-width / 2, "follow_up", "追問", "#2f6fde"), (width / 2, "topic_switch", "換主題", "#e0623a")):
        values = [data["multi_turn"][s][group]["hit@3"] for s in STRATEGIES]
        n = data["multi_turn"][STRATEGIES[0]][group]["n"]
        bars = axes[0].bar([p + offset for p in positions], values, width, label=f"{label}（{n} 段）", color=color)
        axes[0].bar_label(bars, labels=[f"{v:.0%}" for v in values])
    axes[0].set_xticks(list(positions), [names[s] for s in STRATEGIES])
    axes[0].set_ylim(0, 1.3)
    axes[0].legend(loc="upper left", ncol=2)
    axes[0].set_title("多輪對話的 Recall@3：查詢改寫策略")
    labels = ["修正前（未填就排除）", "修正後（未填也保留）"]
    values = [data["criteria"]["strict"]["precision@3"], data["criteria"]["include_unspecified"]["precision@3"]]
    bars = axes[1].bar(labels, values, color=["#9aa3ad", "#2f6fde"])
    axes[1].bar_label(bars, labels=[f"{v:.0%}" for v in values])
    axes[1].set_ylim(0, 1.1)
    axes[1].set_title(f"有條件的查詢 Precision@3（{data['criteria']['strict']['n']} 句）：前 3 名有幾成是對的課")
    fig.tight_layout()
    fig.savefig(OUT / "rewrite_and_filter.png", dpi=160)
    plt.close(fig)


def main():
    import os

    from sqlalchemy import select

    from backend.core.database import SessionLocal
    from backend.models.student import Course
    from backend.services.ai_semantic import embed_texts
    from backend.services.rag_retrieval import build_query, published_course_scores
    from backend.services.recommendation import (
        _apply_required_filters,
        _unsupported,
        parse_criteria,
    )

    version = os.environ.get("AI_COURSE_EMBEDDING_VERSION", "")
    if not version:
        raise SystemExit("AI_COURSE_EMBEDDING_VERSION is required")
    rows = split_queries([json.loads(line) for line in QUERIES.read_text(encoding="utf-8").splitlines() if line.strip()])
    truth = catalog_truth()

    texts = sorted({build_query(row["turns"], s) for row in rows for s in STRATEGIES})
    vectors = {}
    for start in range(0, len(texts), 8):
        batch = texts[start : start + 8]
        embedded = embed_texts(batch)
        if embedded is None:
            raise SystemExit("embedding_gateway_unavailable")
        vectors.update(zip(batch, embedded, strict=True))

    with SessionLocal() as db:
        cache = {}

        def scores_for(text):
            if text not in cache:
                cache[text] = published_course_scores(db, vectors[text], version)
            return cache[text]

        def filtered(criteria, include_unspecified):
            statement = _apply_required_filters(
                select(Course.id).where(Course.status == "published"), criteria, include_unspecified_delivery=include_unspecified
            )
            return set(db.scalars(statement))

        data = {"topic": {}, "multi_turn": {}, "criteria": {}}
        per_query = []
        dev_in_top1, dev_out_top1, test_in_top1, test_out_top1 = [], [], [], []
        dev_relevant_scores, dev_irrelevant_scores = [], []
        topic_results = {"dev": [], "test": []}
        rule_hits = {"dev": [], "test": []}
        for row in rows:
            query = build_query(row["turns"], "follow_up")
            scores = scores_for(query)
            top1 = max(scores.values())
            if row["type"] == "out_of_scope":
                (dev_out_top1 if row["split"] == "dev" else test_out_top1).append(top1)
                rule_hits[row["split"]].append(_unsupported(query))
                per_query.append({"id": row["id"], "split": row["split"], "type": row["type"], "top1": round(top1, 4), "instrument_rule": _unsupported(query)})
                continue
            (dev_in_top1 if row["split"] == "dev" else test_in_top1).append(top1)
            relevant = relevant_ids(row, truth)
            if row["type"] == "topic":
                result = evaluate_one(rank(scores), relevant)
                topic_results[row["split"]].append(result)
                if row["split"] == "dev":
                    for course_id, score in scores.items():
                        (dev_relevant_scores if course_id in relevant else dev_irrelevant_scores).append(score)
                per_query.append({"id": row["id"], "split": row["split"], "type": row["type"], "top1": round(top1, 4), **result})

        data["topic"] = {split: summarize(results) for split, results in topic_results.items()}

        for strategy in STRATEGIES:
            grouped = {"all": [], "follow_up": [], "topic_switch": []}
            for row in rows:
                if row["type"] != "multi_turn":
                    continue
                result = evaluate_one(rank(scores_for(build_query(row["turns"], strategy))), relevant_ids(row, truth))
                grouped["all"].append(result)
                grouped[row["subtype"]].append(result)
            data["multi_turn"][strategy] = {group: summarize(results) for group, results in grouped.items()}

        parse_ok = 0
        for variant, include in (("strict", False), ("include_unspecified", True)):
            results = []
            for row in rows:
                if row["type"] != "criteria":
                    continue
                parsed = parse_criteria(row["turns"][0])
                if variant == "strict":
                    parse_ok += all(parsed.get(k) == v for k, v in row["criteria"].items())
                matching = filtered(parsed, include)
                scores = scores_for(build_query(row["turns"], "follow_up"))
                # 和 course_chat 一樣：符合條件的排前面，再依相似度
                ranking = sorted(scores, key=lambda course_id: (course_id not in matching, -scores[course_id]))
                results.append(evaluate_one(ranking, relevant_ids(row, truth)))
            data["criteria"][variant] = summarize(results)
        data["criteria"]["parse_accuracy"] = parse_ok / data["criteria"]["strict"]["n"]

    threshold = choose_threshold(dev_in_top1, dev_out_top1)
    conservative = conservative_threshold(dev_in_top1, dev_out_top1)

    def combined(split, tau):
        tops = dev_out_top1 if split == "dev" else test_out_top1
        return sum(1 for top, rule in zip(tops, rule_hits[split]) if rule or top < tau) / len(tops)

    data["threshold"] = {
        **threshold,
        "test": gate_rates(test_in_top1, test_out_top1, threshold["tau"]),
        "conservative": {
            **conservative,
            "test": gate_rates(test_in_top1, test_out_top1, conservative["tau"]),
            "reject_with_instrument_rule": {"dev": combined("dev", conservative["tau"]), "test": combined("test", conservative["tau"])},
        },
        "instrument_rule_only_reject": {split: sum(hits) / len(hits) for split, hits in rule_hits.items()},
        "health_project_0.83": {"dev": gate_rates(dev_in_top1, dev_out_top1, 0.83)},
        "in_scope_top1": {"dev_min": min(dev_in_top1), "dev_median": statistics.median(dev_in_top1)},
        "out_scope_top1": {"dev_max": max(dev_out_top1), "dev_median": statistics.median(dev_out_top1)},
    }
    data["meta"] = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "embedding_model": "bge-m3:567m",
        "embedding_version": version,
        "queries": len(rows),
        "split_seed": SEED,
        "dev_ratio": DEV_RATIO,
        "courses_scored": len(next(iter(cache.values()))),
    }
    plots(
        {**data, "dev_in_top1": dev_in_top1, "dev_out_top1": dev_out_top1,
         "dev_relevant_scores": dev_relevant_scores, "dev_irrelevant_scores": dev_irrelevant_scores},
        threshold,
    )
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "metrics.json").write_text(json.dumps({**data, "per_query": per_query}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in data.items() if k != "meta"}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
