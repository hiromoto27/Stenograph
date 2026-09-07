"""Task ranking — LOGIC.md §4–5. Thresholds from LOGIC.md only."""

from __future__ import annotations

from collections import Counter
from typing import Any

from worker.tokens import bag, clamp, cosine, tokenize
from worker.intent import intent_to_dict, parse_speech_intent
from worker.kind import classify_kind

AUTO_THRESHOLD = 0.52  # LOGIC.md §4
AMBIGUOUS_GAP = 0.16  # LOGIC.md §5
AMBIGUOUS_TIGHT = 0.1


def _task_pos_bag(task: dict[str, Any]) -> Counter[str]:
    """Title bag + weighted positive profile (LOGIC.md §6 dict[str,float])."""
    c: Counter[str] = bag(tokenize(str(task.get("title") or "")))
    pos = task.get("positive") or {}
    if isinstance(pos, list):
        from worker.tasks_store import as_weight_dict

        pos = as_weight_dict(pos)
    for tok, w in dict(pos).items():
        try:
            weight = float(w)
        except (TypeError, ValueError):
            weight = 1.0
        s = str(tok).lower().replace("ё", "е")
        if len(s) >= 3:
            c[s] += weight
    return c


def _task_neg_bag(task: dict[str, Any]) -> Counter[str]:
    """Weighted negative profile (LOGIC.md §6 dict[str,float])."""
    c: Counter[str] = Counter()
    neg = task.get("negative") or {}
    if isinstance(neg, list):
        from worker.tasks_store import as_weight_dict

        neg = as_weight_dict(neg)
    for tok, w in dict(neg).items():
        try:
            weight = float(w)
        except (TypeError, ValueError):
            weight = 1.0
        s = str(tok).lower().replace("ё", "е")
        if len(s) >= 3:
            c[s] += weight
    return c


def _embed_bag(task: dict[str, Any]) -> Counter[str]:
    """Bag-of-words stand-in until Chroma (LOGIC.md §4 — keep bag)."""
    c: Counter[str] = bag(tokenize(f"{task.get('title') or ''} {task.get('notes') or ''}"))
    pos = task.get("positive") or {}
    if isinstance(pos, list):
        from worker.tasks_store import as_weight_dict

        pos = as_weight_dict(pos)
    for tok, w in dict(pos).items():
        try:
            weight = float(w)
        except (TypeError, ValueError):
            weight = 1.0
        s = str(tok).lower().replace("ё", "е")
        if len(s) >= 3:
            c[s] += weight
    return c


def rank_tasks(text: str, tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    q_toks = tokenize(text)
    q = bag(q_toks)
    q_set = set(q_toks)

    def _overlap(qs: set[str], ps: set[str]) -> set[str]:
        hits = set(qs & ps)
        for a in qs:
            for b in ps:
                if len(a) >= 4 and len(b) >= 4 and (a.startswith(b) or b.startswith(a)):
                    hits.add(a if a in qs else b)
        return hits

    scored: list[dict[str, Any]] = []
    for t in tasks:
        pos = _task_pos_bag(t)
        neg = _task_neg_bag(t)
        overlap = _overlap(q_set, set(pos.keys()))
        score = clamp(
            cosine(q, pos) - 0.45 * cosine(q, neg) + min(0.22, 0.05 * len(overlap)),
            0.0,
            1.0,
        )
        # neuralBoost stand-in: bag cosine vs title+notes+positive
        emb = cosine(q, _embed_bag(t))
        final = min(1.0, score * 0.7 + emb * 0.3)
        scored.append(
            {
                "task_id": t["task_id"],
                "title": t["title"],
                "score": round(final, 4),
                "overlap": sorted(overlap),
                "links": list(t.get("links") or []),
            }
        )
    scored.sort(key=lambda x: -x["score"])
    return scored


def linked_ambiguous(ranked: list[dict[str, Any]]) -> tuple[bool, str]:
    """LOGIC.md §5."""
    if len(ranked) < 2:
        return False, ""
    a, b = ranked[0], ranked[1]
    if not a.get("overlap") or not b.get("overlap"):
        return False, ""
    gap = abs(float(a["score"]) - float(b["score"]))
    if gap > AMBIGUOUS_GAP:
        return False, ""
    linked = bool(set(a.get("links") or []) & {b["task_id"]}) or bool(
        set(b.get("links") or []) & {a["task_id"]}
    )
    shared = bool(set(a.get("overlap") or []) & set(b.get("overlap") or []))
    if linked or shared or gap < AMBIGUOUS_TIGHT:
        if linked:
            return True, "связи"
        if shared:
            return True, "ключевые слова"
        return True, "нужно подтверждение"
    return False, ""


def apply_feedback(
    tasks: list[dict[str, Any]],
    *,
    chosen_id: str | None,
    utterance: str,
    suggested_ids: list[str],
    mode: str,
) -> None:
    """LOGIC.md §6 — mutate tasks in place (weighted positive/negative profiles)."""
    from worker.tasks_store import as_weight_dict, save_tasks

    toks = tokenize(utterance)
    by_id = {t["task_id"]: t for t in tasks}
    chosen = by_id.get(chosen_id) if chosen_id else None
    if chosen is not None:
        pos = as_weight_dict(chosen.get("positive"))
        chosen["positive"] = pos
        boost = 1.25 if mode == "auto" else 1.0
        for tok in toks:
            pos[tok] = float(pos.get(tok) or 0.0) + boost
        if mode == "auto" or (suggested_ids and chosen_id == suggested_ids[0]):
            chosen["hits"] = int(chosen.get("hits") or 0) + 1
        elif suggested_ids and chosen_id not in suggested_ids[:1]:
            chosen["hits"] = int(chosen.get("hits") or 0) + 1
            top = by_id.get(suggested_ids[0])
            if top is not None:
                top["misses"] = int(top.get("misses") or 0) + 1
        # ask: other candidates get negative; links between chosen and neighbors
        if mode == "ask":
            for sid in suggested_ids:
                if sid == chosen_id:
                    continue
                other = by_id.get(sid)
                if other is None:
                    continue
                neg = as_weight_dict(other.get("negative"))
                other["negative"] = neg
                for tok in toks:
                    neg[tok] = float(neg.get(tok) or 0.0) + 1.0
                if chosen_id not in other.setdefault("links", []):
                    other["links"].append(chosen_id)
                if sid not in chosen.setdefault("links", []):
                    chosen["links"].append(sid)
    save_tasks(tasks)


def suggest(text: str, tasks: list[dict[str, Any]], *, utterance_id: str) -> dict[str, Any]:
    intent = parse_speech_intent(text)
    kind, kind_score = classify_kind(text)
    ranked = rank_tasks(text, tasks)
    top = ranked[:3]
    ambiguous, reason = linked_ambiguous(ranked)
    best = top[0]["score"] if top else 0.0
    auto = (not ambiguous) and best >= AUTO_THRESHOLD and intent.kind != "create_task"

    return {
        "event": "task.suggest",
        "utterance_id": utterance_id,
        "job_id": utterance_id,
        "text": text,
        "candidates": [
            {"task_id": c["task_id"], "title": c["title"], "score": c["score"]} for c in top
        ],
        "allow_none": True,
        "allow_new": True,
        "ambiguous": ambiguous,
        "reason": reason,
        "auto": auto,
        "threshold": AUTO_THRESHOLD,
        "intent": intent_to_dict(intent),
        "kind": kind,
        "kind_score": kind_score,
    }
