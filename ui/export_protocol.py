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

    @property
    def anchor(self) -> str:
        base = self.job_id or self.ts or "line"
        slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", base).strip("-").lower()
        return slug or "line"


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


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
