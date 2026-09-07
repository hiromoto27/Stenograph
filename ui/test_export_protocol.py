"""Smoke tests for ui/export_protocol.py — LOGIC.md §9 (template + package)."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ui.export_protocol import (
    DEFAULT_TEMPLATE,
    ProtocolLine,
    export_package,
    render_sections,
    render_template,
)


def _lines() -> list[ProtocolLine]:
    return [
        ProtocolLine(text="Решили запускать в пятницу", kind="decision", task_id="t1", task_title="Релиз"),
        ProtocolLine(text="Есть риск не успеть с тестами", kind="risk"),
        ProtocolLine(text="Блокер: нет доступа к серверу", kind="blocker"),
        ProtocolLine(text="Просто реплика без задачи", kind="speech"),
    ]


class TestRenderSections(unittest.TestCase):
    def test_decisions_risks_blockers_split_by_kind(self) -> None:
        sections = render_sections(_lines())
        self.assertIn("Решили запускать в пятницу", sections["decisions"])
        self.assertIn("Есть риск не успеть с тестами", sections["risks"])
        self.assertIn("[блокер] Блокер: нет доступа к серверу", sections["risks"])

    def test_unassigned_excludes_task_lines(self) -> None:
        sections = render_sections(_lines())
        self.assertNotIn("Решили запускать в пятницу", sections["unassigned"])
        self.assertIn("Просто реплика без задачи", sections["unassigned"])

    def test_actions_prefixed_with_task_title(self) -> None:
        sections = render_sections(_lines())
        self.assertIn("Релиз: Решили запускать в пятницу", sections["actions"])

    def test_empty_lines_render_placeholder(self) -> None:
        sections = render_sections([])
        for value in sections.values():
            self.assertEqual(value, "- (пусто)")


class TestRenderTemplate(unittest.TestCase):
    def test_all_placeholders_substituted(self) -> None:
        out = render_template(DEFAULT_TEMPLATE, _lines(), title="Летучка")
        self.assertNotIn("{{", out)
        self.assertIn("Летучка", out)


class TestExportPackage(unittest.TestCase):
    def test_bundle_contains_all_documents(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = export_package(_lines(), title="Летучка", out_root=Path(tmp))
            self.assertEqual(
                set(paths),
                {"protocol_md", "protocol_docx", "protocol_html", "digest", "guide_draft"},
            )
            for p in paths.values():
                self.assertTrue(p.exists())

    def test_prunes_packages_beyond_50(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for _ in range(52):
                export_package(_lines(), title="X", out_root=root)
            packages_dir = root / "packages"
            self.assertLessEqual(len(list(packages_dir.iterdir())), 50)


if __name__ == "__main__":
    unittest.main()
