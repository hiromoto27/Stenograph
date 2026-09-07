"""Design tokens from DESIGN.md (Grok Stenograf preview)."""
from __future__ import annotations

import flet as ft

BG = "#0B0C0E"
SURFACE = "#141518"
SURFACE2 = "#1C1D21"
SURFACE3 = "#26272C"
TEXT = "#ECECE8"
MUTED = "#9A9B97"
SUBTLE = "#6E6F6C"
BORDER = "#2A2B2F"
ACCENT = "#ECECE8"
ACCENT_FG = "#0B0C0E"
REC = "#C45C4A"
REC_FG = "#FFF8F6"
OK = "#7D9A78"
WARN = "#C4A574"
RING = "#C8C4BC"


def page_theme(page: ft.Page) -> None:
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = BG
    page.theme = ft.Theme(
        color_scheme=ft.ColorScheme(
            primary=ACCENT,
            on_primary=ACCENT_FG,
            surface=SURFACE,
            on_surface=TEXT,
            outline=BORDER,
            error=REC,
        )
    )
