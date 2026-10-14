from __future__ import annotations

import base64
import importlib.util
import json
import re
import subprocess
import unittest
import zipfile
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGE = PROJECT_ROOT / "format-exporters-v2"
GROUPS = ("images", "documents", "code", "data")


def load_action(group: str):
    path = PACKAGE / group / "functions" / "export_action.py"
    spec = importlib.util.spec_from_file_location(f"v2_export_{group}", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


async def invoke(module, body: dict, selected: str, events: list[dict]):
    async def event_call(event):
        if event.get("type") == "input":
            return selected
        return None

    async def emitter(event):
        events.append(event)

    await module.Action().action(body, __id__="choose", __event_call__=event_call, __event_emitter__=emitter)


def run(coro) -> None:
    """Drive these immediate mock callbacks without opening Windows event-loop sockets."""
    try:
        coro.send(None)
    except StopIteration:
        return
    raise AssertionError("Test callback unexpectedly suspended")


def browser_items(events: list[dict]) -> tuple[str, list[dict]]:
    event = next((item for item in events if item.get("type") == "execute"), None)
    if event is None:
        raise AssertionError(f"No download event: {events!r}")
    code = event["data"]["code"]
    match = re.search(r"const files=(\[.*?\]);(?:const pause|for\()", code)
    if not match:
        raise AssertionError("Could not read artifact descriptors from download code")
    return code, json.loads(match.group(1))


def body(text: str) -> dict:
    return {"id": "a1", "messages": [{"id": "a1", "role": "assistant", "content": text}]}


class MultiArtifactExporterV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        subprocess.run(["python", str(PACKAGE / "build_all.py")], check=True, capture_output=True, text=True)
        cls.modules = {group: load_action(group) for group in GROUPS}

    def test_four_class_buttons_and_format_scope(self):
        expected = {"images": "IMG", "documents": "DOC", "code": "CODE", "data": "DATA"}
        actions = json.loads((PACKAGE / "functions.json").read_text(encoding="utf-8"))
        self.assertEqual({item["id"] for item in actions}, {
            "export_images_menu_v2", "export_documents_menu_v2", "export_code_menu_v2", "export_data_menu_v2",
        })
        for group, module in self.modules.items():
            action = module.Action()
            self.assertEqual(len(action.actions), 1)
            self.assertEqual(action.actions[0]["name"], expected[group])
            self.assertIn("required_open_webui_version: 0.11.3", (PACKAGE / group / "functions/export_action.py").read_text(encoding="utf-8")[:300])
        choices = self.modules["documents"].CHOICES
        self.assertIn("DOCX — один документ", choices)
        self.assertIn("XLSX — отдельная книга на каждую таблицу", choices)
        self.assertIn("XLSX — одна книга, таблицы по листам", choices)
        self.assertIn("PPTX — одна презентация", choices)
        self.assertIn("PDF документа (текст ответа)", choices)
        self.assertIn("Текст (.txt)", choices)
        self.assertTrue(any("Power Query" in key for key in self.modules["code"].CHOICES))

    def test_many_sql_and_bash_blocks_each_get_distinct_timestamped_files(self):
        sql = "\n\n".join(f"```sql\nSELECT {i};\n```" for i in range(1, 6))
        events: list[dict] = []
        run(invoke(self.modules["code"], body(sql), "SQL", events))
        code, files = browser_items(events)
        self.assertEqual(len(files), 5)
        self.assertEqual([item["name"].split("-")[-1].split(".")[0] for item in files], ["01", "02", "03", "04", "05"])
        self.assertTrue(all(re.match(r"sql-\d{8}T\d{6}Z-\d{2}\.sql$", item["name"]) for item in files))
        self.assertEqual([base64.b64decode(item["data"]).strip() for item in files], [f"SELECT {i};".encode() for i in range(1, 6)])
        self.assertIn("await new Promise", code)

        bash = "\n\n".join(f"```bash\necho {i}\n```" for i in range(1, 4))
        events = []
        run(invoke(self.modules["code"], body(bash), "Bash (SH)", events))
        _code, files = browser_items(events)
        self.assertEqual(len(files), 3)
        self.assertTrue(all(item["name"].endswith(".sh") for item in files))

    def test_power_query_aliases_preserve_selected_extension(self):
        events: list[dict] = []
        run(invoke(self.modules["code"], body("```powerquery\nlet Source = 1 in Source\n```"), "Power Query (.pq)", events))
        _, pq_files = browser_items(events)
        self.assertTrue(pq_files[0]["name"].endswith(".pq"))
        events = []
        run(invoke(self.modules["code"], body("```m\nlet Source = 2 in Source\n```"), "Power Query (.m)", events))
        _, m_files = browser_items(events)
        self.assertTrue(m_files[0]["name"].endswith(".m"))

    def test_multiple_data_blocks_and_markdown_tables_export_as_separate_csv_files(self):
        content = "```json\n{\"a\":1}\n```\n\n```json\n{\"b\":2}\n```"
        events: list[dict] = []
        run(invoke(self.modules["data"], body(content), "JSON", events))
        _, files = browser_items(events)
        self.assertEqual(len(files), 2)
        self.assertEqual([json.loads(base64.b64decode(item["data"])) for item in files], [{"a": 1}, {"b": 2}])

        tables = "| A | B |\n|---|---|\n|1|2|\n\n| C | D |\n|---|---|\n|3|4|"
        events = []
        run(invoke(self.modules["data"], body(tables), "CSV", events))
        _, files = browser_items(events)
        self.assertEqual(len(files), 2)
        self.assertTrue(all(item["name"].endswith(".csv") for item in files))

    def test_xlsx_modes_create_one_book_per_table_or_one_combined_book(self):
        content = "# First\n| A | B |\n|---|---|\n|1|2|\n\n# Second\n| C | D |\n|---|---|\n|3|4|"
        office = self.modules["documents"]._office()
        calls: list[tuple[list[dict], str]] = []

        def fake_xlsx(blocks: list[dict], title: str) -> bytes:
            calls.append((blocks, title))
            output = BytesIO()
            with zipfile.ZipFile(output, "w") as workbook:
                workbook.writestr("xl/workbook.xml", "<workbook>" + title + "</workbook>")
            return output.getvalue()

        events: list[dict] = []
        with patch.object(self.modules["documents"], "_office", return_value={**office, "build_xlsx": fake_xlsx}):
            run(invoke(self.modules["documents"], body(content), "XLSX — отдельная книга на каждую таблицу", events))
        _, separate = browser_items(events)
        self.assertEqual(len(separate), 2)
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(len(blocks) == 1 and blocks[0]["t"] == "table" for blocks, _ in calls))
        self.assertTrue(all(item["name"].endswith(".xlsx") for item in separate))
        for item in separate:
            with zipfile.ZipFile(BytesIO(base64.b64decode(item["data"]))) as book:
                self.assertIsNone(book.testzip())
                self.assertIn("xl/workbook.xml", book.namelist())

        events = []
        calls.clear()
        with patch.object(self.modules["documents"], "_office", return_value={**office, "build_xlsx": fake_xlsx}):
            run(invoke(self.modules["documents"], body(content), "XLSX — одна книга, таблицы по листам", events))
        _, combined = browser_items(events)
        self.assertEqual(len(combined), 1)
        self.assertTrue(combined[0]["name"].endswith(".xlsx"))
        self.assertEqual(len(calls), 1)
        self.assertEqual(sum(block["t"] == "table" for block in calls[0][0]), 2)
        with zipfile.ZipFile(BytesIO(base64.b64decode(combined[0]["data"]))) as book:
            workbook = book.read("xl/workbook.xml").decode("utf-8")
            self.assertIn("Таблицы", workbook)

    def test_docx_pptx_and_pdf_are_single_artifact_exports(self):
        content = "# Краткий отчёт\n\nОдна запись для проверки экспорта."
        module = self.modules["documents"]
        office = module._office()
        for selected, extension in (("DOCX — один документ", ".docx"), ("PPTX — одна презентация", ".pptx")):
            events: list[dict] = []
            fake_pptx = lambda _blocks, _title: b"PK\x03\x04pptx-test"
            with patch.object(module, "_office", return_value={**office, "build_pptx": fake_pptx}):
                run(invoke(module, body(content), selected, events))
            _, files = browser_items(events)
            self.assertEqual(len(files), 1)
            self.assertTrue(files[0]["name"].endswith(extension))
            self.assertTrue(base64.b64decode(files[0]["data"]).startswith(b"PK\x03\x04"))

        events = []
        run(invoke(module, body(content), "PDF документа (текст ответа)", events))
        event = next(item for item in events if item.get("type") == "execute")
        code = event["data"]["code"]
        self.assertIn("contentWindow.print()", code)
        self.assertIn("srcdoc", code)
        self.assertIn("Сохранить как PDF", " ".join(item.get("data", {}).get("content", "") for item in events if item.get("type") == "notification"))

    def test_multiple_mermaid_diagrams_and_single_markdown_or_txt(self):
        mermaid = "```mermaid\nflowchart TD\nA-->B\n```\n\n```mermaid\nflowchart LR\nC-->D\n```"
        events: list[dict] = []
        run(invoke(self.modules["documents"], body(mermaid), "VSDX — отдельный файл на каждую Mermaid-диаграмму", events))
        _, diagrams = browser_items(events)
        self.assertEqual(len(diagrams), 2)
        for item in diagrams:
            with zipfile.ZipFile(BytesIO(base64.b64decode(item["data"]))) as package:
                self.assertIsNone(package.testzip())
                self.assertIn("visio/pages/page1.xml", package.namelist())

        for selected, ext in (("Markdown (.md)", ".md"), ("Текст (.txt)", ".txt")):
            events = []
            run(invoke(self.modules["documents"], body("# Заголовок\n\nТекст"), selected, events))
            _, files = browser_items(events)
            self.assertEqual(len(files), 1)
            self.assertTrue(files[0]["name"].endswith(ext))

    def test_multiple_svg_png_and_webp_sources(self):
        svg_text = "```svg\n<svg xmlns=\"http://www.w3.org/2000/svg\"><rect width=\"1\" height=\"1\"/></svg>\n```\n\n```svg\n<svg xmlns=\"http://www.w3.org/2000/svg\"><circle r=\"1\"/></svg>\n```"
        events: list[dict] = []
        run(invoke(self.modules["images"], body(svg_text), "SVG — CorelDRAW (вектор)", events))
        _, svgs = browser_items(events)
        self.assertEqual(len(svgs), 2)
        self.assertTrue(all(item["name"].endswith(".svg") for item in svgs))

        pngs = [b"\x89PNG\r\n\x1a\nfixture1", b"\x89PNG\r\n\x1a\nfixture2"]
        markdown = "\n".join(f"![{i}](data:image/png;base64,{base64.b64encode(data).decode()})" for i, data in enumerate(pngs))
        events = []
        run(invoke(self.modules["images"], body(markdown), "PNG", events))
        _, outputs = browser_items(events)
        self.assertEqual(len(outputs), 2)
        self.assertTrue(all(item["name"].endswith(".png") for item in outputs))

        events = []
        run(invoke(self.modules["images"], body(markdown), "WebP", events))
        webp_code, outputs = browser_items(events)
        self.assertEqual(len(outputs), 2)
        self.assertIn('canvas.toBlob(resolve,mime,0.92)', webp_code)

    def test_raster_formats_convert_multiple_svg_artifacts(self):
        content = "```svg\n<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"8\" height=\"8\"><rect width=\"8\" height=\"8\"/></svg>\n```\n\n```svg\n<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"9\" height=\"9\"><circle cx=\"4\" cy=\"4\" r=\"4\"/></svg>\n```"
        for selected, ext, mime in (("PNG", ".png", '"image/png"'), ("JPG", ".jpg", '"image/jpeg"'), ("WebP", ".webp", '"image/webp"')):
            events: list[dict] = []
            run(invoke(self.modules["images"], body(content), selected, events))
            code, files = browser_items(events)
            self.assertEqual(len(files), 2)
            self.assertTrue(all(item["name"].endswith(ext) for item in files))
            self.assertTrue(all(item["convert_from_svg"] for item in files))
            self.assertIn("new Image()", code)
            self.assertIn(f"const mime={mime}", code)
            self.assertIn('blob.type==="image/svg+xml"', code)

    def test_available_png_or_jpg_sources_are_converted_to_selected_raster(self):
        jpeg = b"\xff\xd8\xff\xe0JPEG_FIXTURE"
        content = f"![photo](data:image/jpeg;base64,{base64.b64encode(jpeg).decode()})"
        events: list[dict] = []
        run(invoke(self.modules["images"], body(content), "PNG", events))
        code, files = browser_items(events)
        self.assertEqual(len(files), 1)
        self.assertTrue(files[0]["name"].endswith(".png"))
        self.assertEqual(files[0]["mime"], "image/jpeg")
        self.assertIn('const mime="image/png"', code)

        png = b"\x89PNG\r\n\x1a\nPNG_FIXTURE"
        content = f"![photo](data:image/png;base64,{base64.b64encode(png).decode()})"
        events = []
        run(invoke(self.modules["images"], body(content), "JPG", events))
        code, files = browser_items(events)
        self.assertEqual(len(files), 1)
        self.assertTrue(files[0]["name"].endswith(".jpg"))
        self.assertEqual(files[0]["mime"], "image/png")
        self.assertIn('const mime="image/jpeg"', code)

    def test_install_remove_and_function_bundle_versions(self):
        for script_name in ("install-functions.sh", "remove-functions.sh"):
            script = (PACKAGE / script_name).read_text(encoding="utf-8")
            self.assertIn('SCRIPT_VERSION="2026.10.11.3"', script)
        manager = (PACKAGE / "manage-functions.py").read_text(encoding="utf-8")
        self.assertIn("export_code_menu_v2", manager)
        self.assertNotIn('"export_code_menu"', manager)
        self.assertIn('version="%(prog)s 2026.10.11.3"', manager)
        self.assertIn("DOCX/PPTX по одному файлу", manager)
        for group in GROUPS:
            record = json.loads((PACKAGE / group / "functions/functions.json").read_text(encoding="utf-8"))[0]
            self.assertIn("_v2", record["id"])
            self.assertEqual(record["content"], (PACKAGE / group / "functions/export_action.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
