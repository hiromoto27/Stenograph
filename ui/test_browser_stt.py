"""Tests for ui/browser_stt.py — engine=browser (Edge WebView2 / Web Speech).

Covers the actual flet-webview-all 0.1.8 API surface: the control class is
FletWebviewAll (not WebView), JS talks back through a named
javascript_channels entry (not window.chrome.webview.postMessage), and
run_javascript is a coroutine that must go through page.run_task. All three
were wrong in an earlier version of this module and would have silently
no-op'd on real hardware — resolve_stt_engine would say "browser available"
while build_webview quietly returned (None, None, None).
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ui.browser_stt import (
    JS_CHANNEL,
    build_webview,
    resolve_stt_engine,
    should_fallback_to_whisper,
    webview_available,
)

try:
    import flet_webview_all  # noqa: F401

    HAS_WEBVIEW_PKG = True
except Exception:
    HAS_WEBVIEW_PKG = False


class TestResolveEngine(unittest.TestCase):
    def test_whisper_stays_whisper(self) -> None:
        self.assertEqual(resolve_stt_engine("whisper"), ("whisper", ""))

    def test_empty_defaults_to_whisper(self) -> None:
        self.assertEqual(resolve_stt_engine(""), ("whisper", ""))

    def test_browser_with_webview_available(self) -> None:
        self.assertEqual(resolve_stt_engine("browser", has_webview=True), ("browser", ""))

    def test_browser_without_webview_falls_back(self) -> None:
        engine, reason = resolve_stt_engine("browser", has_webview=False)
        self.assertEqual(engine, "whisper")
        self.assertIn("Whisper", reason)

    def test_browser_defers_to_webview_available_probe(self) -> None:
        with mock.patch("ui.browser_stt.webview_available", return_value=False):
            self.assertEqual(resolve_stt_engine("browser"), resolve_stt_engine("browser", has_webview=False))


class TestFallbackErrors(unittest.TestCase):
    def test_known_fallback_errors(self) -> None:
        for err in ("not-allowed", "service-not-allowed", "audio-capture", "network", "language-not-supported"):
            self.assertTrue(should_fallback_to_whisper(err), err)

    def test_unknown_error_does_not_fall_back(self) -> None:
        self.assertFalse(should_fallback_to_whisper("aborted"))

    def test_none_or_empty(self) -> None:
        self.assertFalse(should_fallback_to_whisper(None))
        self.assertFalse(should_fallback_to_whisper(""))


class TestWebviewAvailableWithoutPackage(unittest.TestCase):
    def test_import_error_reports_unavailable(self) -> None:
        with mock.patch.dict(sys.modules, {"flet_webview_all": None}):
            self.assertFalse(webview_available())

    def test_build_webview_returns_none_triplet_without_package(self) -> None:
        with mock.patch.dict(sys.modules, {"flet_webview_all": None}):
            control, start, stop = build_webview(mock.MagicMock(), lambda payload: None)
        self.assertEqual((control, start, stop), (None, None, None))


@unittest.skipUnless(HAS_WEBVIEW_PKG, "flet-webview-all not installed")
class TestBuildWebviewWithPackage(unittest.TestCase):
    def test_control_class_is_flet_webview_all(self) -> None:
        control, _, _ = build_webview(mock.MagicMock(), lambda payload: None)
        self.assertEqual(type(control).__name__, "FletWebviewAll")

    def test_registers_expected_js_channel(self) -> None:
        control, _, _ = build_webview(mock.MagicMock(), lambda payload: None)
        self.assertEqual(control.javascript_channels, [JS_CHANNEL])

    def test_allows_webview_permissions_for_mic(self) -> None:
        # Denied by default per flet-webview-all; must be explicitly opted in
        # or SpeechRecognition's getUserMedia request is silently refused.
        control, _, _ = build_webview(mock.MagicMock(), lambda payload: None)
        self.assertTrue(control.allow_webview_permissions)

    def test_html_embeds_the_matching_channel_name(self) -> None:
        control, _, _ = build_webview(mock.MagicMock(), lambda payload: None)
        self.assertIn(f"window.{JS_CHANNEL}", control.html)

    def test_start_schedules_run_javascript_via_page_run_task(self) -> None:
        page = mock.MagicMock()
        control, start, stop = build_webview(page, lambda payload: None)
        start("u-42")
        page.run_task.assert_called_once()
        handler, js = page.run_task.call_args.args
        self.assertEqual(handler, control.run_javascript)
        self.assertIn("u-42", js)
        self.assertIn("stenografStart", js)

    def test_stop_schedules_run_javascript_via_page_run_task(self) -> None:
        page = mock.MagicMock()
        control, start, stop = build_webview(page, lambda payload: None)
        stop()
        page.run_task.assert_called_once()
        handler, js = page.run_task.call_args.args
        self.assertEqual(handler, control.run_javascript)
        self.assertIn("stenografStop", js)

    def test_on_message_receives_parsed_payload_from_matching_channel(self) -> None:
        received: list[dict] = []
        control, _, _ = build_webview(mock.MagicMock(), received.append)
        evt = SimpleNamespace(
            channel_name=JS_CHANNEL,
            message_body='{"type": "final", "utterance_id": "u-1", "text": "привет", "engine": "browser"}',
        )
        control.on_javascript_message(evt)
        self.assertEqual(received, [{"type": "final", "utterance_id": "u-1", "text": "привет", "engine": "browser"}])

    def test_ignores_messages_from_a_different_channel(self) -> None:
        received: list[dict] = []
        control, _, _ = build_webview(mock.MagicMock(), received.append)
        evt = SimpleNamespace(channel_name="SomeOtherChannel", message_body='{"type": "final", "text": "x"}')
        control.on_javascript_message(evt)
        self.assertEqual(received, [])

    def test_ignores_malformed_json_without_raising(self) -> None:
        received: list[dict] = []
        control, _, _ = build_webview(mock.MagicMock(), received.append)
        evt = SimpleNamespace(channel_name=JS_CHANNEL, message_body="not json")
        control.on_javascript_message(evt)  # must not raise
        self.assertEqual(received, [])


if __name__ == "__main__":
    unittest.main()
