"""Sanity checks for ui/guides.py content — DESIGN.md §5 «Гайды»."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ui.guides import GUIDES


class TestGuidesContent(unittest.TestCase):
    def test_at_least_one_guide_per_tab(self) -> None:
        # Студия, «Куда отнести?», Карта, Сроки, Протокол, Данные/поиск/Compact, troubleshooting
        self.assertGreaterEqual(len(GUIDES), 7)

    def test_titles_unique(self) -> None:
        titles = [g.title for g in GUIDES]
        self.assertEqual(len(titles), len(set(titles)))

    def test_every_guide_has_title_subtitle_and_steps(self) -> None:
        for g in GUIDES:
            self.assertTrue(g.title.strip())
            self.assertTrue(g.subtitle.strip())
            self.assertTrue(g.steps)
            for step in g.steps:
                self.assertTrue(step.strip())


if __name__ == "__main__":
    unittest.main()
