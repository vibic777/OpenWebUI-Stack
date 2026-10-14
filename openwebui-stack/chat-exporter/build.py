#!/usr/bin/env python3
"""Embed document export helpers in the whole-chat Action."""
from __future__ import annotations

import base64
import ast
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
VERSION = "1.0.2"
TEMPLATE = HERE / "export_chat.template.py"
SOURCE = HERE / "functions" / "export_chat.py"
HELPER = HERE.parent / "document-exporter" / "functions" / "export_documents.py"


def chat_helper_source() -> bytes:
    if not HELPER.is_file():
        tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == "HELPER_B64"
                for target in node.targets
            ):
                return base64.b64decode(ast.literal_eval(node.value))
        raise FileNotFoundError(HELPER)
    source = HELPER.read_text(encoding="utf-8")
    pdf_start = source.index("# 5. PDF (stdlib writer + Noto font shipped with Open WebUI)")
    txt_match = re.search(r"(?ms)^def build_txt\(.*?(?=^def build_csv\(|\Z)", source[pdf_start:])
    if not txt_match:
        raise ValueError("Could not extract the plain-text helper")
    text_builder = txt_match.group(0).rstrip()
    source = source[:pdf_start].rstrip() + "\n\n\n" + text_builder + "\n"
    source = source.replace(
        "title: Export Documents (DOCX / XLSX / PPTX / VSDX / PDF / MD / TXT / CSV)",
        "title: Chat Export Helpers (DOCX / XLSX / PPTX / TXT)",
    )
    source = source.replace(
        "description: Document export Action with eight buttons: DOCX, XLSX, PPTX, VSDX, PDF, MD, TXT and CSV. Runs offline.",
        "description: Formatting helpers used by the whole-chat exporter.",
    )
    if "pdf" in source.casefold():
        raise ValueError("PDF code leaked into the chat-export helper bundle")
    return source.encode("utf-8")


def build() -> None:
    template = TEMPLATE.read_text(encoding="utf-8")
    encoded = base64.b64encode(chat_helper_source()).decode("ascii")
    output = template.replace("@@HELPER_B64@@", encoded)
    if "@@HELPER_B64@@" in output:
        raise ValueError("Unresolved helper marker")
    SOURCE.write_text(output, encoding="utf-8", newline="\n")
    manifest = [{
        "id": "export_entire_chat",
        "name": "Экспорт всего чата",
        "content": output,
            "meta": {"description": "Экспорт всей истории текущего чата в один DOCX, PPTX, XLSX, Markdown, TXT или JSON.", "manifest": {}},
        "is_active": True,
        "is_global": True,
    }]
    (HERE / "functions.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    installer = HERE / "functions" / "install_functions.py"
    installer.write_text(
        re_version(installer.read_text(encoding="utf-8"), VERSION), encoding="utf-8", newline="\n"
    )
    for script_name in ("install-functions.sh", "remove-functions.sh"):
        script = HERE / script_name
        script.write_text(
            re_version(script.read_text(encoding="utf-8"), VERSION), encoding="utf-8", newline="\n"
        )
    print(f"Built export_entire_chat ({len(output):,} bytes)")


def re_version(text: str, version: str) -> str:
    text = re.sub(r'(?<=SCRIPT_VERSION=")\d+\.\d+\.\d+(?=")', version, text)
    text = re.sub(r'(?<=version="%(prog)s )\d+\.\d+\.\d+', version, text)
    return text


if __name__ == "__main__":
    build()
