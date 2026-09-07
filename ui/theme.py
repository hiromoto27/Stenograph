"""Dark Studio theme tokens (Flet)."""
from __future__ import annotations

import flet as ft

BG = "#0a0a0a"
SURFACE = "#141414"
SURFACE2 = "#1c1c1c"
BORDER = "#2a2a2a"
TEXT = "#f5f5f5"
MUTED = "#a3a3a3"
ACCENT = "#fafafa"
ACCENT_FG = "#0a0a0a"


def page_theme(page: ft.Page) -> None:
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = BG
    page.padding = 0
