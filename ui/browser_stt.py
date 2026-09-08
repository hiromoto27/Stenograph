"""Optional WebView host (flet-webview-all) for Web Speech (engine=browser).

Requires `flet-webview-all>=0.1.8` on Windows + Edge WebView2 runtime — the
Flutter `webview_all` plugin this wraps uses WebView2 as its Windows backend
(README: "Windows 10 version 1809+ (WebView2)"), so the mic + ru-RU + interim
results here are the same underlying engine as the Edge preview.
If WebView/mic is missing, callers must fall back to whisper — never silent.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

import flet as ft

OnMessage = Callable[[dict[str, Any]], None]

HTML_PATH = Path(__file__).resolve().parent / "assets" / "browser_stt.html"

# Must match the channel the page calls in ui/assets/browser_stt.html
# (window.<JS_CHANNEL>.postMessage(...)), and what's passed to
# javascript_channels= below — flet-webview-all bridges JS->Python
# through a named channel, not window.chrome.webview.postMessage.
JS_CHANNEL = "StenografBridge"

# Web Speech errors that mean "use Whisper instead", not "keep waiting"
_FALLBACK_ERRORS = {
    "not-allowed",
    "service-not-allowed",
    "audio-capture",
    "network",
    "language-not-supported",
}


def webview_available() -> bool:
    try:
        from flet_webview_all import FletWebviewAll  # noqa: F401

        return True
    except Exception:
        return False


def resolve_stt_engine(preferred: str, *, has_webview: bool | None = None) -> tuple[str, str]:
    """Return (effective_engine, human reason). Never returns browser without WebView."""
    pref = (preferred or "whisper").strip().lower()
    if pref != "browser":
        return "whisper", ""
    ok = webview_available() if has_webview is None else bool(has_webview)
    if not ok:
        return (
            "whisper",
            "Browser недоступен (нет flet-webview-all / WebView2) — переключился на Whisper",
        )
    return "browser", ""


def should_fallback_to_whisper(error: str | None) -> bool:
    if not error:
        return False
    low = str(error).strip().lower()
    return low in _FALLBACK_ERRORS or low.startswith("not-allowed")


def build_webview(page: ft.Page, on_message: OnMessage, *, width: int = 1, height: int = 1):
    """Return a (control, start_fn, stop_fn) or (None, None, None).

    `page` is needed because FletWebviewAll's JS-execution methods
    (run_javascript) are coroutines — they only actually run when scheduled
    via page.run_task, calling them directly just builds an un-awaited
    coroutine and does nothing.
    """
    try:
        from flet_webview_all import FletWebviewAll
    except Exception:
        return None, None, None

    html = HTML_PATH.read_text(encoding="utf-8") if HTML_PATH.exists() else "<html></html>"

    def _on_js(e: Any) -> None:
        if getattr(e, "channel_name", JS_CHANNEL) != JS_CHANNEL:
            return
        raw = getattr(e, "message_body", None) or ""
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return
        if isinstance(payload, dict):
            on_message(payload)

    wv = FletWebviewAll(
        html=html,
        width=width,
        height=height,
        javascript_enabled=True,
        javascript_channels=[JS_CHANNEL],
        # WebView-layer mic gate — denied by default. OS-level mic permission
        # (Windows Settings > Privacy > Microphone) is a separate prerequisite,
        # same one sounddevice capture already needs for the Whisper path.
        allow_webview_permissions=True,
        on_javascript_message=_on_js,
    )

    def start(utterance_id: str) -> None:
        js = f"window.stenografStart({json.dumps(utterance_id)});"
        page.run_task(wv.run_javascript, js)

    def stop() -> None:
        page.run_task(wv.run_javascript, "window.stenografStop();")

    return wv, start, stop
