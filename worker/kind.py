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
    (r"блокер", 0.9),
    (r"риск", 0.8),
    (r"проблема", 0.7),
    (r"застрял", 0.75),
    (r"не\s+успеваем", 0.8),
]
_NEGATE = re.compile(r"не\s+решил|надо\s+утвердить|не\s+утверд", re.I)

KIND_THRESHOLD = 0.6  # LOGIC.md §7


def classify_kind(text: str) -> tuple[str, float]:
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
    if dec >= KIND_THRESHOLD and dec >= risk:
        return "decision", dec
    if risk >= KIND_THRESHOLD:
        return "risk", risk
    return "speech", 0.0
