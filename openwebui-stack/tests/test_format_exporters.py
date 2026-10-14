from __future__ import annotations

import base64
import importlib.util
import json
import os
import re
import subprocess
import sys
import unittest
import zipfile
from io import BytesIO
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = PROJECT_ROOT / "format-exporters"
GROUPS = {
    "images": ("export_images_menu", "WebP"),
    "documents": ("export_documents_menu", "VSDX"),
    "code": ("export_code_menu", "VBA Office (BAS)"),
    "data": ("export_data_menu", "JSON"),
}


def load_action(folder: str):
    path = PACKAGE_ROOT / folder / "functions" / "export_action.py"
    spec = importlib.util.spec_from_file_location(f"test_format_export_{folder}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def invoke(module, body, selected, events):
    async def event_call(event):
        if event.get("type") == "input":
            assert event["data"]["input"]["type"] == "select"
            return selected
        return None

    async def emitter(event):
        events.append(event)

    await module.Action().action(body, __id__="choose", __event_call__=event_call, __event_emitter__=emitter)


def run_immediate(coro) -> None:
    """Run async Actions whose mocked callbacks complete without suspending."""
    try:
        coro.send(None)
    except StopIteration:
        return
    raise AssertionError("Test callback unexpectedly suspended")


def downloaded(events) -> tuple[str, bytes]:
    event = next((e for e in events if e.get("type") == "execute"), None)
    if event is None:
        raise AssertionError(f"No browser download event; exporter emitted: {events!r}")
    code = event["data"]["code"]
    match = re.search(r'atob\("([A-Za-z0-9+/=]+)"\)', code)
    return code, base64.b64decode(match.group(1)) if match else b""


class StandaloneFormatExporterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.getenv("FORMAT_EXPORTERS_SKIP_BUILD") != "1":
            subprocess.run(["python", str(PACKAGE_ROOT / "build_all.py")], check=True, capture_output=True, text=True)
        cls.modules = {folder: load_action(folder) for folder in GROUPS}

    def test_four_standalone_functions_have_one_menu_button_and_minimum_version(self):
        ids = set()
        icon_urls = set()
        action_labels = {"images": "IMG", "documents": "DOC", "code": "CODE", "data": "DATA"}
        expected_counts = {"images": 4, "documents": 7, "code": 16, "data": 11}
        for folder, (fid, label) in GROUPS.items():
            module = self.modules[folder]
            action = module.Action()
            self.assertEqual(len(action.actions), 1)
            self.assertEqual(action.actions[0]["name"], action_labels[folder])
            self.assertTrue(action.actions[0]["icon_url"].startswith("data:image/svg+xml;base64,"))
            icon_urls.add(action.actions[0]["icon_url"])
            self.assertIn(label, module.CHOICES)
            self.assertEqual(len(module.CHOICES), expected_counts[folder])
            self.assertIn("required_open_webui_version: 0.11.3", (PACKAGE_ROOT / folder / "functions/export_action.py").read_text(encoding="utf-8")[:400])
            self.assertEqual(json.loads((PACKAGE_ROOT / folder / "functions/functions.json").read_text(encoding="utf-8"))[0]["id"], fid)
            installer_path = PACKAGE_ROOT / folder / "functions/install_functions.py"
            installer_spec = importlib.util.spec_from_file_location(f"test_installer_{folder}", installer_path)
            installer = importlib.util.module_from_spec(installer_spec)
            sys.modules[installer_spec.name] = installer
            installer_spec.loader.exec_module(installer)
            self.assertEqual(installer.version_tuple("0.11.3"), (0, 11, 3))
            self.assertEqual(installer.version_tuple("v0.11.4"), (0, 11, 4))
            self.assertLess(installer.version_tuple("0.11.2"), installer.MINIMUM_VERSION)
            ids.add(fid)
        self.assertEqual(len(ids), 4)
        self.assertEqual(len(icon_urls), 4)

    def test_svg_menu_delegates_safe_svg_download(self):
        body = {"id": "m1", "messages": [{"id": "m1", "role": "assistant", "content": '```svg\n<svg xmlns="http://www.w3.org/2000/svg"><rect width="10" height="10"/></svg>\n```'}]}
        events = []
        run_immediate(invoke(self.modules["images"], body, "SVG", events))
        code, raw = downloaded(events)
        self.assertIn(".svg", code)
        self.assertIn(b"<svg", raw)

    def test_webp_menu_emits_browser_conversion_with_raster_validation(self):
        png = b"\x89PNG\r\n\x1a\n" + b"valid-fixture"
        uri = "data:image/png;base64," + base64.b64encode(png).decode()
        body = {"id": "m1", "messages": [{"id": "m1", "role": "assistant", "content": f"![fixture]({uri})"}]}
        events = []
        run_immediate(invoke(self.modules["images"], body, "WebP", events))
        code, _ = downloaded(events)
        self.assertIn('canvas.toBlob(resolve,"image/webp",0.92)', code)
        self.assertIn("Источник должен быть корректным PNG или JPEG", code)
        self.assertIn(".webp", code)

    def test_vsdx_is_a_valid_package_from_constrained_mermaid(self):
        mermaid = """flowchart TD
A[Заявка] --> B{Проверена?}
B -->|Да| C[Согласование]
B -->|Нет| D[Доработка] --> A
"""
        body = {"id": "m1", "messages": [{"id": "m1", "role": "assistant", "content": f"# Согласование\n\n```mermaid\n{mermaid}\n```"}]}
        events = []
        run_immediate(invoke(self.modules["documents"], body, "VSDX", events))
        _code, raw = downloaded(events)
        with zipfile.ZipFile(BytesIO(raw)) as package:
            self.assertIsNone(package.testzip())
            names = set(package.namelist())
            self.assertTrue({"[Content_Types].xml", "_rels/.rels", "docProps/app.xml", "docProps/core.xml", "docProps/custom.xml", "visio/document.xml", "visio/windows.xml", "visio/pages/pages.xml", "visio/pages/_rels/page1.xml.rels", "visio/pages/page1.xml"} <= names)
            self.assertIn("<DocumentSettings", package.read("visio/document.xml").decode("utf-8"))
            self.assertIn("<Shape", package.read("visio/pages/page1.xml").decode("utf-8"))

    def test_docx_xlsx_and_pptx_produce_office_packages(self):
        content = "# Проверка экспорта\n\nКороткий текст.\n\n| Поле | Значение |\n|---|---|\n| Номер | 42 |\n"
        body = {"id": "m1", "messages": [{"id": "m1", "role": "assistant", "content": content}]}
        for choice, required_part, dependency in (("DOCX", "word/document.xml", "docx"), ("XLSX", "xl/workbook.xml", "openpyxl"), ("PPTX", "ppt/presentation.xml", "pptx")):
            with self.subTest(choice=choice):
                events = []
                run_immediate(invoke(self.modules["documents"], body, choice, events))
                if not any(e.get("type") == "execute" for e in events):
                    notice = " ".join(e.get("data", {}).get("content", "") for e in events)
                    self.assertIn(dependency, notice.lower())
                    continue
                _code, raw = downloaded(events)
                with zipfile.ZipFile(BytesIO(raw)) as package:
                    self.assertIsNone(package.testzip())
                    self.assertIn(required_part, package.namelist())

    def test_code_and_data_actions_download_only_the_selected_block(self):
        cases = (
            ("code", "VBA Office (BAS)", "```vba\nSub Hello()\nEnd Sub\n```", b"Sub Hello()", ".bas"),
            ("code", "TypeScript (TS)", "```typescript\nconst answer: number = 42;\n```", b"const answer", ".ts"),
            ("data", "JSON", '```json\n{"request":42}\n```', b'"request":42', ".json"),
        )
        for folder, choice, content, expected, extension in cases:
            with self.subTest(choice=choice):
                body = {"id": "m1", "messages": [{"id": "m1", "role": "assistant", "content": content}]}
                events = []
                run_immediate(invoke(self.modules[folder], body, choice, events))
                code, raw = downloaded(events)
                self.assertIn(expected, raw)
                self.assertIn(extension, code)

    def test_data_validators_cover_formats_and_reject_invalid_json(self):
        module = self.modules["data"]
        valid = {
            "jsonl": '{"id":1}\n{"id":2}', "xml": "<root/>", "yml": "items:\n  - one",
            "toml": 'name = "test"', "ini": "[app]\nname=test", "conf": "path=/srv/app",
            "env": "MODE=test", "properties": "name=test", "csv": "a,b\n1,2", "tsv": "a\tb\n1\t2",
        }
        for fmt, content in valid.items():
            with self.subTest(fmt=fmt):
                module._validate_data(content, fmt)
        with self.assertRaises(Exception):
            module._validate_data('{bad json}', "json")

    def test_cancelled_menu_emits_no_file(self):
        module = self.modules["code"]
        events = []

        async def event_call(_event): return False
        async def emitter(event): events.append(event)

        run_immediate(module.Action().action({"messages": []}, __id__="choose", __event_call__=event_call, __event_emitter__=emitter))
        self.assertFalse(any(e.get("type") == "execute" for e in events))

    def test_install_and_remove_scripts_have_valid_bash_syntax(self):
        bash = "C:/Program Files/Git/bin/bash.exe" if Path("C:/Program Files/Git/bin/bash.exe").is_file() else None
        if not bash:
            self.skipTest("Bash is not available for syntax checks")
        probe = subprocess.run([bash, "--version"], capture_output=True, text=True)
        if probe.returncode:
            self.skipTest("The installed Bash executable cannot start in this environment")
        for folder in GROUPS:
            for script in ("install-functions.sh", "remove-functions.sh"):
                subprocess.run([str(bash), "-n", str(PACKAGE_ROOT / folder / script)], check=True, capture_output=True, text=True)
        for script in ("install-functions.sh", "remove-functions.sh"):
            subprocess.run([str(bash), "-n", str(PACKAGE_ROOT / script)], check=True, capture_output=True, text=True)
        compile((PACKAGE_ROOT / "manage-functions.py").read_text(encoding="utf-8"), "manage-functions.py", "exec")


if __name__ == "__main__":
    unittest.main()
