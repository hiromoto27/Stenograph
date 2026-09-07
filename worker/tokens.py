"""Tokenize / stem / cosine — LOGIC.md §3–4. Do not invent thresholds."""

from __future__ import annotations

import math
import re
from collections import Counter

# One-pass RU endings, longest first (LOGIC.md §3)
_STEM_ENDS = (
    "ами", "ями", "ого", "ему", "ыми", "ими",
    "ов", "ев", "ей", "ах", "ях", "ам", "ям", "ом", "ем",
    "ой", "ый", "ий", "ая", "ое", "ые", "ие",
    "ть", "ти", "ла", "ли", "ло", "ка", "ки",
)

_STOP = {
    "это", "эта", "эти", "тот", "та", "те", "как", "что", "чтобы", "для",
    "при", "про", "над", "под", "без", "или", "либо", "если", "когда",
    "уже", "еще", "ещё", "только", "также", "тоже", "быть", "был", "была",
    "были", "есть", "нет", "не", "ни", "на", "но", "да", "же", "ли",
    "мы", "вы", "он", "она", "они", "я", "ты", "мне", "нас", "вам",
    "его", "ее", "её", "их", "все", "всё", "весь", "своя", "свой",
    "надо", "нужно", "необходимо",
    "очень", "просто", "сейчас", "тогда", "тут", "там", "здесь",
}

_WORD = re.compile(r"[a-zа-яё0-9]+", re.IGNORECASE)


def stem_token(tok: str) -> str:
    if len(tok) < 5:
        return tok
    for end in _STEM_ENDS:
        if tok.endswith(end) and len(tok) - len(end) >= 3:
            return tok[: -len(end)]
    return tok


def tokenize(text: str) -> list[str]:
    raw = (text or "").lower().replace("ё", "е")
    out: list[str] = []
    for m in _WORD.finditer(raw):
        w = m.group(0)
        if len(w) < 3 or w in _STOP:
            continue
        st = stem_token(w)
        out.append(st)
        # light RU inflection: also keep head without trailing vowel (LOGIC stems + practical)
        if len(st) >= 5 and st[-1] in "аеиоуыя":
            out.append(st[:-1])
    return out


def bag(tokens: list[str]) -> Counter[str]:
    return Counter(tokens)


def cosine(a: Counter[str], b: Counter[str]) -> float:
    if not a or not b:
        return 0.0
    keys = set(a) | set(b)
    dot = sum(a[k] * b[k] for k in keys)
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    if na <= 0 or nb <= 0:
        return 0.0
    return dot / (na * nb)


def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))
