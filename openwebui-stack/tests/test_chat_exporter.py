from __future__ import annotations

import base64
import importlib.util
import json
import re
import unittest
import zipfile
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACTION = ROOT / "chat-exporter" / "functions" / "export_chat.py"


def load_module():
    spec = importlib.util.spec_from_file_location("openwebui_chat_export", ACTION)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class ChatExporterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()

    def call_action(self, selected: str, messages: list[dict], title="Проверка чата"):
        events = []

        async def event_call(event):
            if event.get("type") == "input":
                return selected
            return None

        async def emitter(event):
            events.append(event)

        self.drain(self.module.Action().action(
            {"chat": {"title": title}, "messages": messages}, __id__="choose",
            __event_call__=event_call, __event_emitter__=emitter,
        ))
        return events

    @staticmethod
    def download_from(events):
        execute = next(event for event in events if event["type"] == "execute")
        code = execute["data"]["code"]
        match = re.search(r'const b=atob\("([A-Za-z0-9+/=]+)"\)', code)
        if not match:
            return code, None
        return code, base64.b64decode(match.group(1))

    @staticmethod
    def drain(coro):
        try:
            coro.send(None)
        except StopIteration:
            return
        raise AssertionError("Mock async callback unexpectedly suspended")

    def test_all_requested_formats_are_available(self):
        formats = set(self.module.FORMATS.values())
        self.assertEqual(formats, {"docx", "pptx", "xlsx", "md", "txt", "json"})
        helper_source = base64.b64decode(self.module.HELPER_B64).decode("utf-8")
        self.assertNotIn("pdf", helper_source.casefold())

    def test_chat_action_has_priority_after_v2_icons_and_white_x_icon(self):
        action = self.module.Action()
        self.assertEqual(action.valves.priority, 20)
        self.assertEqual(action.actions[0]["name"], "Экспорт чата")
        icon = action.actions[0]["icon_url"]
        self.assertTrue(icon.startswith("data:image/svg+xml;base64,"))
        svg = base64.b64decode(icon.split(",", 1)[1]).decode("utf-8")
        self.assertIn(">X</text>", svg)
        self.assertIn('fill="#fff"', svg)

    def test_markdown_and_text_include_entire_ordered_history(self):
        messages = [
            {"role": "user", "content": "Вопрос пользователя"},
            {"role": "assistant", "content": "Ответ ассистента"},
            {"role": "system", "content": "Не включать system"},
        ]
        for choice, expected in (("Markdown — вся история (.md)", "## Пользователь".encode()),
                                 ("Обычный текст — вся история (.txt)", "Пользователь".encode())):
            with self.subTest(choice=choice):
                events = self.call_action(choice, messages)
                _code, raw = self.download_from(events)
                self.assertIsNotNone(raw)
                self.assertIn(expected, raw)
                self.assertLess(raw.index("Вопрос".encode()), raw.index("Ответ".encode()))
                self.assertNotIn("Не включать".encode(), raw)
                self.assertEqual(sum(event["type"] == "execute" for event in events), 1)

    def test_json_is_one_file_with_original_chat_message_objects(self):
        messages = [{"role": "user", "content": "Привет", "id": "m1"},
                    {"role": "assistant", "content": "Ответ", "id": "m2"},
                    {"role": "system", "content": "служебное"}]
        events = self.call_action("JSON — сообщения чата (.json)", messages)
        _code, raw = self.download_from(events)
        decoded = json.loads(raw)
        self.assertEqual([item["id"] for item in decoded], ["m1", "m2"])
        self.assertEqual(sum(event["type"] == "execute" for event in events), 1)

    def test_office_formats_make_single_workbook_or_document(self):
        messages = [{"role": "user", "content": "Покажи исходные данные"},
                    {"role": "assistant", "content": "# Ответ\n\n| Имя | Значение |\n|---|---:|\n| A | 10 |"}]
        docx_choice = next(choice for choice, fmt in self.module.FORMATS.items() if fmt == "docx")
        events = self.call_action(docx_choice, messages)
        code, raw = self.download_from(events)
        self.assertIn(".docx", code)
        self.assertIsNotNone(raw)
        with zipfile.ZipFile(BytesIO(raw)) as archive:
            self.assertTrue(archive.namelist())
        self.assertEqual(sum(event["type"] == "execute" for event in events), 1)

    def test_xlsx_reports_missing_optional_dependency(self):
        if importlib.util.find_spec("openpyxl"):
            self.skipTest("openpyxl is installed; real workbook generation is covered by the success path")
        xlsx_choice = next(choice for choice, fmt in self.module.FORMATS.items() if fmt == "xlsx")
        events = self.call_action(xlsx_choice, [
            {"role": "user", "content": "Покажи данные"},
            {"role": "assistant", "content": "| Имя | Значение |\n|---|---:|\n| A | 10 |"},
        ])
        self.assertFalse(any(event["type"] == "execute" for event in events))
        self.assertTrue(any("openpyxl" in event.get("data", {}).get("content", "")
                            for event in events if event["type"] == "notification"))

    def test_pdf_format_is_not_offered_or_executed(self):
        events = self.call_action("PDF — сохранить через браузер", [
            {"role": "user", "content": "Вопрос"},
            {"role": "assistant", "content": "Ответ"},
        ])
        self.assertFalse(any(event["type"] == "execute" for event in events))
        self.assertTrue(any("Неизвестный формат" in event.get("data", {}).get("content", "")
                            for event in events if event["type"] == "notification"))

    def test_manifest_matches_action_source(self):
        package = ROOT / "chat-exporter"
        manifest = json.loads((package / "functions.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest[0]["id"], "export_entire_chat")
        self.assertEqual(manifest[0]["content"], ACTION.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
