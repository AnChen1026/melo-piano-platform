"""Semantic ranking for already-authorized, filtered course candidates."""

import math


def cosine(left, right):
    if (
        not isinstance(left, list)
        or not isinstance(right, list)
        or not left
        or len(left) != len(right)
    ):
        return None
    if any(
        isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x)
        for x in [*left, *right]
    ):
        return None
    left_norm = math.sqrt(sum(x * x for x in left))
    right_norm = math.sqrt(sum(x * x for x in right))
    if not left_norm or not right_norm:
        return None
    return sum(a * b for a, b in zip(left, right, strict=True)) / (
        left_norm * right_norm
    )


def rank_candidates(candidates, query):
    """Stable sort candidates by optional valid embedding; never remove candidates."""

    def score(row):
        metadata = row[1]
        value = cosine(metadata.get("score"), query) if metadata else None
        return (value is not None, value if value is not None else 0)

    return sorted(candidates, key=score, reverse=True)


def course_text(course):
    return "\n".join(
        str(value).strip()
        for value in (course.title, course.style, course.description)
        if value and str(value).strip()
    )[:1000]


def course_hash(course):
    import hashlib

    return hashlib.sha256(course_text(course).encode("utf-8")).hexdigest()


def embed_texts(texts):
    import os
    from urllib.parse import urlsplit

    import httpx

    url = os.environ.get("AI_COURSE_GATEWAY_URL", "").rstrip("/")
    token = os.environ.get("AI_COURSE_GATEWAY_TOKEN", "")
    version = os.environ.get("AI_COURSE_EMBEDDING_VERSION", "")
    parsed = urlsplit(url)
    if (
        not parsed.hostname
        or parsed.username
        or parsed.query
        or parsed.fragment
        or len(token) < 32
        or len(version) != 64
        or any(c not in "0123456789abcdef" for c in version)
        or (
            parsed.scheme != "https"
            and not (
                parsed.scheme == "http"
                and parsed.hostname in {"localhost", "127.0.0.1", "::1", "host.docker.internal"}
            )
        )
    ):
        return None
    try:
        response = httpx.post(
            url + "/api/embed",
            headers={"Authorization": "Bearer " + token, "X-Embedding-Digest": version},
            json={"model": "bge-m3:567m", "input": texts, "truncate": False},
            timeout=45,
        )
        response.raise_for_status()
        vectors = response.json()["embeddings"]
        if len(vectors) != len(texts) or any(
            len(v) != 1024 or cosine(v, v) is None for v in vectors
        ):
            return None
        return vectors
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return None


def course_similarities(db, course_ids, query_vector, version):
    """在資料庫用 pgvector 算餘弦相似度（1 − <=> 距離），回傳 {課程 id: (內容雜湊, 相似度)}。

    只算傳進來的候選課程：硬條件已先用 SQL 篩過，這裡是精確計算，不經過近似索引，
    所以不會因為近似搜尋漏掉符合條件的課。
    """
    from sqlalchemy import Float, select

    from backend.models.rag_document import SOURCE_COURSE, RagDocument

    if not course_ids:
        return {}
    distance = RagDocument.embedding.op("OPERATOR(extensions.<=>)", return_type=Float)(query_vector)
    statement = select(
        RagDocument.course_id, RagDocument.content_hash, (1 - distance).label("score")
    ).where(
        RagDocument.source_type == SOURCE_COURSE,
        RagDocument.course_id.in_(course_ids),
        RagDocument.model_version == version,
    )
    return {course_id: (content_hash, float(score)) for course_id, content_hash, score in db.execute(statement)}


def rank_public_courses_with_status(db, rows, query):
    """Rank only provided published candidates, ignoring stale or wrong-version vectors."""
    import os

    version = os.environ.get("AI_COURSE_EMBEDDING_VERSION", "")
    if not query or not rows:
        return rows, "ready"
    if not version:
        return rows, "unavailable"
    query_vectors = embed_texts([query[:1000]])
    if not query_vectors:
        return rows, "unavailable"
    found = course_similarities(db, [row[0].id for row in rows], query_vectors[0], version)
    scores = {}
    for row in rows:
        course = row[0]
        hit = found.get(course.id)
        # 課程改過但還沒重建索引：舊向量不代表現在的內容，不拿來排序
        if hit and hit[0] == course_hash(course):
            scores[course.id] = hit[1]
    status = "ready" if len(scores) == len(rows) else ("partial" if scores else "unavailable")
    # 有向量的依相似度由高到低；沒有向量的保留原順序排在後面，不會被刪掉
    ranked = sorted(rows, key=lambda row: (row[0].id in scores, scores.get(row[0].id, 0.0)), reverse=True)
    return ranked, status


def rank_public_courses(db, rows, query):
    return rank_public_courses_with_status(db, rows, query)[0]
