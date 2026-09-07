"""Archive search — LOGIC.md §12. Same tokenizer as the classifier."""

from __future__ import annotations

from typing import Any

from worker.tokens import tokenize

TOP_N = 20
TASK_BONUS = 0.15


def search_archive(
    query: str,
    lines: list[dict[str, Any]],
    tasks: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Rank archived utterances by share of matched stems; +0.15 when the
    line's task also matches the query (LOGIC.md §12). Returns top 20.

    ``lines`` items need a "text" key and may carry "task_id"; anything
    else (job_id, ts, kind, …) is passed through into the result row.
    """
    q_stems = set(tokenize(query))
    if not q_stems:
        return []

    task_hits: set[str] = set()
    if tasks:
        for t in tasks:
            title_stems = set(tokenize(str(t.get("title") or "")))
            pos_stems = {str(k).lower().replace("ё", "е") for k in dict(t.get("positive") or {})}
            if q_stems & (title_stems | pos_stems):
                task_hits.add(str(t.get("task_id") or ""))

    scored: list[dict[str, Any]] = []
    for line in lines:
        text = str(line.get("text") or "")
        stems = set(tokenize(text))
        if not stems:
            continue
        matched = q_stems & stems
        if not matched:
            continue
        score = len(matched) / len(q_stems)
        if line.get("task_id") and str(line["task_id"]) in task_hits:
            score += TASK_BONUS
        row = dict(line)
        row["score"] = round(min(1.0, score), 4)
        scored.append(row)

    scored.sort(key=lambda r: -r["score"])
    return scored[:TOP_N]
