"""Utterance kind — LOGIC.md §7."""

from __future__ import annotations

import re

_DECISION = [
    (r"утвердили", 0.9),
    (r"приняли\s+решение", 0.9),
    (r"постановили", 0.85),
    (r"договорились", 0.85),
    (r"решили", 0.8),
    (r"согласовали", 0.75),
]
_RISK = [
    (r"может\s+сорваться", 0.85),
    (r"риск", 0.8),
    (r"проблема", 0.7),
    (r"опасно", 0.7),
]
_BLOCKER = [
    (r"блокер", 0.9),
    (r"стоп[-\s]?фактор", 0.9),
    (r"заблок", 0.85),
    (r"жд[её]м\s+согласован", 0.8),
    (r"не\s+успеваем", 0.8),
    (r"застрял", 0.75),
]
# Negation / unfinished decision → multiply decision score ×0.15 (LOGIC.md §7)
_NEGATE = re.compile(
    r"не\s+решил|надо\s+утвердить|не\s+утверд|нужно\s+решить|ещ[её]\s+не\s+решили",
    re.I,
)

KIND_THRESHOLD = 0.6  # LOGIC.md §7


def classify_kind(text: str) -> tuple[str, float]:
    """Return (kind, score). Kinds: decision | risk | blocker | speech."""
    t = text or ""
    dec = 0.0
    for pat, sc in _DECISION:
        if re.search(pat, t, re.I):
            dec = max(dec, sc)
    if _NEGATE.search(t):
        dec *= 0.15

    risk = 0.0
    for pat, sc in _RISK:
        if re.search(pat, t, re.I):
            risk = max(risk, sc)

    blocker = 0.0
    for pat, sc in _BLOCKER:
        if re.search(pat, t, re.I):
            blocker = max(blocker, sc)

    best_kind, best_score = max(
        (("decision", dec), ("risk", risk), ("blocker", blocker)),
        key=lambda x: x[1],
    )
    if best_score >= KIND_THRESHOLD:
        return best_kind, best_score
    return "speech", 0.0
