"""Offline checks for the combined document/image Action and VSDX package."""
from __future__ import annotations

import base64
import posixpath
import sys
import unittest
import xml.etree.ElementTree as ET
import zipfile
from io import BytesIO
from pathlib import Path

FUNCTIONS = Path(__file__).resolve().parents[1] / "open-webui" / "functions"
sys.path.insert(0, str(FUNCTIONS))
import export_office as exporter  # noqa: E402


def run_immediate(coro):
    """Run an async Action with immediate test callbacks without opening sockets."""
    try:
        coro.send(None)
    except StopIteration:
        return
    raise AssertionError("Test callback unexpectedly suspended")


class ExportActionTests(unittest.TestCase):
    def test_buttons_are_documents_and_images_only(self):
        expected = {"docx", "xlsx", "pptx", "vsdx", "pdf", "md", "txt", "csv", "svg", "png", "jpg"}
        self.assertEqual(set(exporter.FORMATS), expected)
        self.assertEqual({button["id"] for button in exporter.Action().actions}, expected)
        self.assertFalse(expected & {"ps1", "sh", "py", "json", "xml", "yml", "html", "css", "js", "php"})

    def test_csv_and_txt(self):
        blocks = exporter.parse_markdown('| Имя | Комментарий |\n|---|---|\n| Иван | сказал "да, ок" |')
        self.assertEqual(exporter.build_csv(blocks).decode(), 'Имя,Комментарий\r\nИван,"сказал ""да, ок"""\r\n')
        txt = exporter.build_txt(exporter.parse_markdown("# Заголовок\n\nТекст **важно**." )).decode()
        self.assertIn("Заголовок", txt)
        self.assertIn("Текст важно", txt)

    def test_embedded_image_exports_and_svg_safety(self):
        cases = (
            ("svg", '```svg\n<svg xmlns="http://www.w3.org/2000/svg"><text>ok</text></svg>\n```', "image/svg+xml"),
            ("png", "data:image/png;base64," + base64.b64encode(bytes([137, 80, 78, 71, 13, 10, 26, 10]) + b"valid").decode(), "image/png"),
            ("jpg", "data:image/jpeg;base64," + base64.b64encode(bytes([255, 216, 255]) + b"valid").decode(), "image/jpeg"),
        )
        action = exporter.Action()
        for fmt, content, mime in cases:
            with self.subTest(fmt=fmt):
                events = []
                async def emit(event):
                    events.append(event)
                body = {"id": "m", "messages": [{"id": "m", "role": "assistant", "content": content}]}
                run_immediate(action.action(body, __id__=fmt, __event_emitter__=emit))
                code = next(event["data"]["code"] for event in events if event.get("type") == "execute")
                self.assertIn(mime, code)
        with self.assertRaisesRegex(ValueError, "активный"):
            exporter._safe_svg('<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>')


class VsdxTests(unittest.TestCase):
    def test_unsupported_mermaid_is_reported_instead_of_silently_falling_back(self):
        blocks = exporter.parse_markdown("```mermaid\nsequenceDiagram\nA->>B: hello\n```")
        with self.assertRaisesRegex(ValueError, "flowchart TD/LR"):
            exporter.build_vsdx(blocks, "Unsupported")

    def test_mermaid_flowchart_produces_well_formed_visio_package(self):
        mermaid = """flowchart TD
            A[Заявка] --> B{Проверена?}
            B -->|Да| C[Подписание]
            B -->|Нет| D[Доработка] --> A
        """
        graph = exporter.parse_mermaid(mermaid)
        self.assertIsNotNone(graph)
        self.assertEqual(len(graph["nodes"]), 4)
        self.assertEqual(len(graph["edges"]), 4)
        raw = exporter.build_vsdx(exporter.parse_markdown(f"```mermaid\n{mermaid}\n```"), "Согласование")
        with zipfile.ZipFile(BytesIO(raw)) as package:
            self.assertIsNone(package.testzip())
            names = set(package.namelist())
            self.assertTrue({"[Content_Types].xml", "_rels/.rels", "docProps/app.xml", "docProps/core.xml", "docProps/custom.xml", "visio/document.xml", "visio/windows.xml", "visio/pages/pages.xml", "visio/pages/_rels/page1.xml.rels", "visio/pages/page1.xml"} <= names)
            self.assertIn("<DocumentSettings", package.read("visio/document.xml").decode("utf-8"))
            roots = {name: ET.fromstring(package.read(name)) for name in names if name.endswith((".xml", ".rels"))}
            for name, root in roots.items():
                if not name.endswith(".rels"):
                    continue
                owner_dir = "" if name == "_rels/.rels" else name.removesuffix("/_rels/" + posixpath.basename(name))
                for rel in root:
                    self.assertIn(posixpath.normpath(posixpath.join(owner_dir, rel.attrib["Target"])), names)
            text = " ".join(node.text or "" for node in roots["visio/pages/page1.xml"].iter() if node.tag.endswith("}Text"))
            self.assertIn("Заявка", text)
            self.assertIn("Проверена?", text)
            self.assertIn("Подписание", text)


if __name__ == "__main__":
    unittest.main()
