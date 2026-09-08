"""Offline protocol export: DOCX + interactive HTML (TOC, anchors)."""
from __future__ import annotations

import html
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class ProtocolLine:
    """One protocol utterance."""

    text: str
    job_id: str = ""
    backend: str = ""
    ts: str = ""
    meeting_id: str = ""
    kind: str = "speech"  # decision | risk | blocker | speech — LOGIC.md §7
    kind_score: float = 0.0
    task_id: str = ""
    task_title: str = ""

    @property
    def anchor(self) -> str:
        base = self.job_id or self.ts or "line"
        slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", base).strip("-").lower()
        return slug or "line"


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")


def export_docx(lines: list[ProtocolLine], dest: Path, *, title: str = "Протокол встречи") -> Path:
    from docx import Document

    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    doc = Document()
    doc.add_heading(title, level=0)
    doc.add_paragraph(f"Экспорт: {datetime.now().astimezone().strftime('%Y-%m-%d %H:%M')}")
    doc.add_heading("Оглавление", level=1)
    for i, line in enumerate(lines, start=1):
        label = line.job_id or line.ts or f"#{i}"
        preview = (line.text[:80] + "…") if len(line.text) > 80 else line.text
        doc.add_paragraph(f"{i}. [{label}] {preview}", style="List Number")
    doc.add_heading("Протокол", level=1)
    for i, line in enumerate(lines, start=1):
        meta = " · ".join(x for x in (line.job_id, line.backend, line.ts) if x)
        heading = f"{i}. {meta}" if meta else f"{i}."
        doc.add_heading(heading, level=2)
        doc.add_paragraph(line.text)
    doc.save(dest)
    return dest


def export_html(lines: list[ProtocolLine], dest: Path, *, title: str = "Протокол встречи") -> Path:
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    toc_items: list[str] = []
    body_items: list[str] = []
    used: dict[str, int] = {}
    for i, line in enumerate(lines, start=1):
        a = line.anchor
        if a in used:
            used[a] += 1
            a = f"{a}-{used[a]}"
        else:
            used[a] = 1
        label = html.escape(line.job_id or line.ts or f"#{i}")
        preview = html.escape((line.text[:80] + "…") if len(line.text) > 80 else line.text)
        toc_items.append(f'<li><a href="#{a}">{i}. [{label}] {preview}</a></li>')
        meta = " · ".join(html.escape(x) for x in (line.job_id, line.backend, line.ts) if x)
        body_items.append(
            f'<section id="{a}" class="utt">'
            f"<h2>{i}. {meta or 'реплика'}</h2>"
            f"<p>{html.escape(line.text)}</p>"
            f'<p class="back"><a href="#toc">↑ к оглавлению</a></p>'
            f"</section>"
        )
    exported = html.escape(datetime.now().astimezone().strftime("%Y-%m-%d %H:%M"))
    doc = f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>{html.escape(title)}</title>
  <style>
    :root {{ font-family: system-ui, sans-serif; line-height: 1.45; }}
    body {{ max-width: 52rem; margin: 1.5rem auto; padding: 0 1rem; }}
    #toc {{ background: #f4f4f5; padding: 1rem 1.25rem; border-radius: 8px; }}
    .utt {{ border-top: 1px solid #e4e4e7; padding: 1rem 0; }}
    .utt h2 {{ font-size: 1.05rem; margin: 0 0 0.5rem; }}
    .back {{ font-size: 0.85rem; }}
    a {{ color: #1d4ed8; }}
  </style>
</head>
<body>
  <h1>{html.escape(title)}</h1>
  <p>Экспорт: {exported} · офлайн</p>
  <nav id="toc">
    <h2>Оглавление</h2>
    <ol>
      {''.join(toc_items) or '<li>(пусто)</li>'}
    </ol>
  </nav>
  <main>
    {''.join(body_items) or '<p>Нет реплик.</p>'}
  </main>
</body>
</html>
"""
    dest.write_text(doc, encoding="utf-8")
    return dest


# LOGIC.md §9 — template placeholders
DEFAULT_TEMPLATE = """{{title}}
{{date}}

## Задачи
{{tasks}}

## Решения
{{decisions}}

## Риски и блокеры
{{risks}}

## Действия
{{actions}}

## Без задачи
{{unassigned}}
"""


def _bullet_list(items: list[str], *, empty: str = "(пусто)") -> str:
    if not items:
        return f"- {empty}"
    return "\n".join(f"- {item}" for item in items)


def render_sections(lines: list[ProtocolLine]) -> dict[str, str]:
    """LOGIC.md §9 — split a protocol into template sections."""
    decisions = [l.text for l in lines if l.kind == "decision"]
    risks = [l.text for l in lines if l.kind == "risk"]
    blockers = [l.text for l in lines if l.kind == "blocker"]
    unassigned = [l.text for l in lines if not l.task_id]
    actions = [f"{l.task_title or l.task_id}: {l.text}" for l in lines if l.task_id]
    task_titles = sorted({l.task_title or l.task_id for l in lines if l.task_id})
    risk_block = _bullet_list(risks) if risks else ""
    blocker_block = _bullet_list([f"[блокер] {b}" for b in blockers]) if blockers else ""
    risks_section = "\n".join(x for x in (risk_block, blocker_block) if x) or "- (пусто)"
    return {
        "tasks": _bullet_list(task_titles),
        "decisions": _bullet_list(decisions),
        "risks": risks_section,
        "unassigned": _bullet_list(unassigned),
        "actions": _bullet_list(actions),
    }


def render_template(
    template: str,
    lines: list[ProtocolLine],
    *,
    title: str = "Протокол встречи",
    date: str | None = None,
) -> str:
    sections = render_sections(lines)
    stamp = date or datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")
    out = template
    for key, value in {**sections, "title": title, "date": stamp}.items():
        out = out.replace("{{" + key + "}}", value)
    return out


def export_digest(lines: list[ProtocolLine], dest: Path, *, title: str = "Протокол встречи") -> Path:
    """Короткая выжимка: счётчики + решения/риски/блокеры одной строкой каждое."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    sections = render_sections(lines)
    counts = (
        f"Реплик: {len(lines)} · решений: {sum(1 for l in lines if l.kind == 'decision')} · "
        f"рисков: {sum(1 for l in lines if l.kind == 'risk')} · "
        f"блокеров: {sum(1 for l in lines if l.kind == 'blocker')}"
    )
    body = (
        f"# {title} — выжимка\n\n{counts}\n\n"
        f"## Решения\n{sections['decisions']}\n\n"
        f"## Риски и блокеры\n{sections['risks']}\n\n"
        f"## Действия\n{sections['actions']}\n"
    )
    dest.write_text(body, encoding="utf-8")
    return dest


def export_guide_draft(lines: list[ProtocolLine], dest: Path, *, title: str = "Протокол встречи") -> Path:
    """Черновик гайда: пронумерованные действия из реплик, отнесённых к задачам."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    steps = [l for l in lines if l.task_id]
    body_lines = [f"# {title} — черновик гайда", ""]
    if not steps:
        body_lines.append("Нет реплик, отнесённых к задачам.")
    else:
        for i, l in enumerate(steps, start=1):
            body_lines.append(f"{i}. **{l.task_title or l.task_id}** — {l.text}")
    dest.write_text("\n".join(body_lines) + "\n", encoding="utf-8")
    return dest


def _prune_old_packages(root: Path, *, keep: int = 50) -> None:
    """LOGIC.md §9/§14 — cap stored protocol packages at 50."""
    if not root.exists():
        return
    packages = sorted((p for p in root.iterdir() if p.is_dir()), key=lambda p: p.stat().st_mtime)
    for stale in packages[:-keep] if len(packages) > keep else []:
        for f in stale.glob("*"):
            f.unlink(missing_ok=True)
        stale.rmdir()


def export_package(
    lines: list[ProtocolLine],
    *,
    title: str = "Протокол встречи",
    template: str = DEFAULT_TEMPLATE,
    out_root: Path | None = None,
) -> dict[str, Path]:
    """LOGIC.md §9 — протокол + действия + выжимка + черновик гайда, до 50 пакетов."""
    stamp = _now_stamp()
    root = (out_root or default_export_dir()) / "packages" / stamp
    root.mkdir(parents=True, exist_ok=True)

    protocol_md = root / "protocol.md"
    protocol_md.write_text(render_template(template, lines, title=title), encoding="utf-8")

    paths = {
        "protocol_md": protocol_md,
        "protocol_docx": export_docx(lines, root / "protocol.docx", title=title),
        "protocol_html": export_html(lines, root / "protocol.html", title=title),
        "digest": export_digest(lines, root / "digest.md", title=title),
        "guide_draft": export_guide_draft(lines, root / "guide-draft.md", title=title),
    }
    _prune_old_packages(root.parent, keep=50)
    return paths


def default_export_dir() -> Path:
    local = Path.home() / "AppData" / "Local" / "Stenograf" / "exports"
    if (Path.home() / "AppData").exists():
        return local
    return Path.home() / ".local" / "share" / "Stenograf" / "exports"


def export_both(lines: list[ProtocolLine], *, title: str = "Протокол встречи") -> tuple[Path, Path]:
    stamp = _now_stamp()
    out = default_export_dir()
    docx_path = export_docx(lines, out / f"protocol-{stamp}.docx", title=title)
    html_path = export_html(lines, out / f"protocol-{stamp}.html", title=title)
    return docx_path, html_path


def list_packages(root: Path | None = None) -> list[Path]:
    """Packages written by export_package(), newest first."""
    base = (root or default_export_dir()) / "packages"
    if not base.exists():
        return []
    return sorted((p for p in base.iterdir() if p.is_dir()), key=lambda p: p.stat().st_mtime, reverse=True)


def package_preview(pkg_dir: Path) -> tuple[str, str]:
    """(title, date) from a package's protocol.md — first two lines of DEFAULT_TEMPLATE."""
    md = pkg_dir / "protocol.md"
    title, date = "Протокол", ""
    if md.exists():
        lines = md.read_text(encoding="utf-8").splitlines()
        if lines and lines[0].strip():
            title = lines[0].strip()
        if len(lines) > 1 and lines[1].strip():
            date = lines[1].strip()
    return title, date
