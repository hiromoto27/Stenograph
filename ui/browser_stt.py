"""Optional Edge/WebView2 host for Web Speech (engine=browser).

Requires `flet-webview-all` on Windows + WebView2 runtime. Without it the UI
falls back to a status message; whisper path stays available.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

OnMessage = Callable[[dict[str, Any]], None]

HTML_PATH = Path(__file__).resolve().parent / "assets" / "browser_stt.html"


def webview_available() -> bool:
    try:
        import flet_webview_all  # noqa: F401
        return True
    except Exception:
        return False


def build_webview(on_message: OnMessage, *, width: int = 1, height: int = 1):
    """Return a (control, start_fn, stop_fn) or (None, None, None)."""
    try:
        from flet_webview_all import WebView
    except Exception:
        return None, None, None

    html = HTML_PATH.read_text(encoding="utf-8") if HTML_PATH.exists() else "<html></html>"

    def _on_js(e):  # type: ignore[no-untyped-def]
        raw = getattr(e, "message_body", None) or getattr(e, "data", None) or ""
        if not isinstance(raw, str):
            raw = str(raw)
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return
        if isinstance(payload, dict):
            on_message(payload)

    wv = WebView(
        html=html,
        width=width,
        height=height,
        javascript_enabled=True,
        on_javascript_message=_on_js if hasattr(WebView, "__init__") else None,
    )
    # Best-effort attach common callback names across package versions
    for attr in ("on_javascript_message", "on_web_message", "on_message"):
        if hasattr(wv, attr):
            setattr(wv, attr, _on_js)

    def start(utterance_id: str) -> None:
        js = f"window.stenografStart({json.dumps(utterance_id)});"
        for meth in ("run_javascript", "eval_js", "execute_javascript"):
            fn = getattr(wv, meth, None)
            if callable(fn):
                try:
                    fn(js)
                    return
                except Exception:
                    pass

    def stop() -> None:
        for meth in ("run_javascript", "eval_js", "execute_javascript"):
            fn = getattr(wv, meth, None)
            if callable(fn):
                try:
                    fn("window.stenografStop();")
                    return
                except Exception:
                    pass

    return wv, start, stop
