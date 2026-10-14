#!/usr/bin/env python3
"""Build the v2 four-class multi-artifact exporter package."""
from __future__ import annotations

import base64
import ast
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent
VERSION = "2026.10.11.3"

GROUPS = {
    "images": {
        "id": "export_images_menu_v2", "name": "Экспорт изображений V2 (IMG)",
        "priority": 13,
        "description": "Экспортирует SVG, EPS, DXF, векторный PDF, PNG/JPG/BMP/GIF/WebP локально в браузере.",
        "button": "IMG", "icon": ("#7C3AED", "I"),
        "choices": {
            "SVG — CorelDRAW (вектор)": "svg", "PDF рисунка из SVG (вектор)": "svg_pdf",
            "EPS — Encapsulated PostScript": "eps", "DXF — AutoCAD Drawing Exchange": "dxf",
            "PNG": "png", "JPG": "jpg", "BMP": "bmp", "GIF — анимация из кадров": "gif", "WebP": "webp",
        },
    },
    "documents": {
        "id": "export_documents_menu_v2", "name": "Экспорт документов V2 (DOC)",
        "priority": 12,
        "description": "DOCX/PPTX/PDF отчёта, XLSX, VSDX, Draw.io (.drawio), BPMN (.bpmn), Markdown и TXT.",
        "button": "DOC", "icon": ("#2563EB", "D"),
        "choices": {
            "DOCX — один документ": "docx",
            "XLSX — отдельная книга на каждую таблицу": "xlsx_split",
            "XLSX — одна книга, таблицы по листам": "xlsx_all",
            "PPTX — одна презентация": "pptx",
            "VSDX — отдельный файл на каждую Mermaid-диаграмму": "vsdx",
            "Draw.io (.drawio) — редактируемая схема": "drawio",
            "BPMN (.bpmn) — процессная схема": "bpmn",
            "PDF документа (текст ответа)": "pdf",
            "Markdown (.md)": "md", "Текст (.txt)": "txt",
        },
    },
    "code": {
        "id": "export_code_menu_v2", "name": "Экспорт кода V2 (CODE)",
        "priority": 10,
        "description": "Экспортирует все fenced-блоки выбранного языка, каждый отдельным файлом.",
        "button": "CODE", "icon": ("#059669", "C"),
        "choices": {
            "PowerShell (PS1)": "ps1", "Bash (SH)": "sh", "Python (PY)": "py",
            "VBA Office (BAS)": "vba", "JavaScript (JS)": "js", "TypeScript (TS)": "ts",
            "PHP": "php", "HTML": "html", "CSS": "css", "Java": "java", "C": "c",
            "C++": "cpp", "C#": "cs", "Go": "go", "Rust": "rs", "SQL": "sql",
            "Pascal (.pas)": "pascal:pas", "QBasic (.bas)": "qbasic:bas", "Assembler (.asm)": "asm:asm",
            "Fortran 90+ (.f90)": "fortran:f90", "Lisp (.lisp)": "lisp:lisp",
            "Delphi / Object Pascal (.pas)": "delphi:pas", "AutoIt v3 (.au3)": "autoit:au3",
            "Batch (.bat)": "bat:bat", "Command script (.cmd)": "cmd:cmd",
            "PlantUML (.puml)": "puml", "Graphviz DOT (.dot)": "dot",
            "Power Query (.pq)": "powerquery:pq", "Power Query (.m)": "powerquery:m",
        },
    },
    "data": {
        "id": "export_data_menu_v2", "name": "Экспорт данных V2 (DATA)",
        "priority": 11,
        "description": "Экспортирует все блоки данных выбранного формата в отдельные файлы.",
        "button": "DATA", "icon": ("#D97706", "D"),
        "choices": {
            "JSON": "json", "JSON Lines (JSONL)": "jsonl", "XML": "xml",
            "YAML (YML)": "yml", "TOML": "toml", "INI": "ini", "CONF": "conf",
            "ENV": "env", "Properties": "properties", "CSV": "csv", "TSV": "tsv",
        },
    },
}

BUTTON_TEMPLATE = (HERE / "action_template.py").read_text(encoding="utf-8")
OFFICE_SOURCE = (PROJECT_ROOT / "open-webui/functions/export_office.py").read_bytes()
IMAGES_PATH = PROJECT_ROOT / "image-exporter/functions/export_images.py"
if IMAGES_PATH.is_file():
    IMAGES_SOURCE = IMAGES_PATH.read_bytes()
else:
    # The standalone release omits the upstream helper folder; the built-in
    # Action package contains the exact source needed to reproduce the bundle.
    artifact = HERE / "images/functions/export_action.py"
    tree = ast.parse(artifact.read_text(encoding="utf-8"))
    IMAGES_SOURCE = next(
        base64.b64decode(ast.literal_eval(node.value))
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "IMAGES_B64" for target in node.targets)
    )


def build() -> None:
    office_b64 = base64.b64encode(OFFICE_SOURCE).decode("ascii")
    images_b64 = base64.b64encode(IMAGES_SOURCE).decode("ascii")
    functions: list[dict] = []
    for group, spec in GROUPS.items():
        icon_svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
            f'<rect x="1" y="1" width="30" height="30" rx="8" fill="{spec["icon"][0]}"/>'
            f'<text x="16" y="21" text-anchor="middle" font-family="Arial,sans-serif" '
            f'font-size="16" font-weight="700" fill="white">{spec["icon"][1]}</text></svg>'
        )
        replacements = {
            "@@NAME@@": spec["name"], "@@DESCRIPTION@@": spec["description"],
            "@@GROUP@@": repr(group), "@@CHOICES@@": repr(spec["choices"]),
            "@@PRIORITY@@": str(spec["priority"]),
            "@@BUTTON@@": spec["button"], "@@OFFICE_B64@@": office_b64,
            "@@IMAGES_B64@@": images_b64,
            "@@ICON_URL@@": "data:image/svg+xml;base64," + base64.b64encode(icon_svg.encode()).decode("ascii"),
        }
        source = BUTTON_TEMPLATE
        for old, new in replacements.items():
            source = source.replace(old, new)
        if re.search(r"@@[A-Z_]+@@", source):
            raise ValueError(f"Unresolved marker in {group}")
        package = HERE / group
        functions_dir = package / "functions"
        functions_dir.mkdir(parents=True, exist_ok=True)
        (functions_dir / "export_action.py").write_text(source, encoding="utf-8", newline="\n")
        functions.append({
            "id": spec["id"], "name": spec["name"], "content": source,
            "meta": {"description": spec["description"], "manifest": {}},
            "is_active": True, "is_global": True,
        })
        (functions_dir / "functions.json").write_text(
            json.dumps([functions[-1]], ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        readme = (
            f"# {spec['name']}\n\n"
            "Одна кнопка класса. Экспортируется ответ, под которым нажали кнопку. "
            "Один найденный артефакт даёт один файл; несколько артефактов — отдельные файлы "
            "с одной UTC-меткой времени, порядковым номером и расширением формата. "
            "Разрешите множественные загрузки для Open WebUI, если этого попросит браузер.\n\n"
            "Установка всех четырёх кнопок: `../install-functions.sh`. Удаление только V2: "
            "`../remove-functions.sh`. Скрипты V2 используют собственные ID с суффиксом `_v2` "
            "и не изменяют прежние экспортёры.\n"
        )
        (package / "README.md").write_text(readme, encoding="utf-8", newline="\n")
        print(f"Built {group}: {spec['id']} ({len(source):,} bytes)")

    (HERE / "functions.json").write_text(json.dumps(functions, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    package_readme = '''# Экспортёры V2 для Open WebUI

Версия: `{VERSION}`. Это отдельный набор из четырёх кнопок IMG, DOC, CODE и DATA. Старые Actions остаются без изменений. Каждая кнопка работает с сообщением ассистента, под которым её нажали. Если формат встречается несколько раз в ответе, каждый артефакт скачивается отдельным файлом с общей UTC-меткой времени и порядковым номером.

| Кнопка | Форматы | Поведение |
|---|---|---|
| IMG | SVG (CorelDRAW), PDF рисунка из SVG, EPS, DXF, PNG, JPG, BMP, GIF, WebP | SVG можно открыть в CorelDRAW и сохранить как CDR. SVG можно скачать либо напечатать в PDF рисунка через диалог браузера. EPS и DXF скачиваются как fenced-блоки соответствующих форматов. PNG/JPG/BMP/WebP скачиваются или создаются из SVG в браузере. GIF объединяет несколько исходных изображений или SVG-кадров в анимацию. |
| DOC | DOCX, XLSX, PPTX, VSDX, Draw.io (.drawio), BPMN (.bpmn), PDF документа, Markdown, TXT | DOCX/PPTX — по одному файлу на ответ. PDF документа печатает форматированный текст ответа. Это отдельный вариант PDF по сравнению с IMG → PDF рисунка из SVG. XLSX: отдельная книга для каждой Markdown-таблицы или одна книга со всеми таблицами на отдельных листах. VSDX — по Mermaid-диаграмме; Draw.io и BPMN — отдельные редактируемые XML-файлы из одноимённых fenced-блоков. |
| CODE | PS1, SH, PY, VBA/BAS, JS, TS, PHP, HTML, CSS, Java, C, C++, C#, Go, Rust, SQL, Pascal, QBasic, Assembler, Fortran, Lisp, Delphi/Object Pascal, AutoIt v3, BAT, CMD, PlantUML, Graphviz DOT, Power Query | Каждый code fence выбранного языка становится отдельным файлом. QBasic и VBA выбираются по разным fenced-меткам, хотя оба имеют расширение `.bas`. Pascal и Delphi/Object Pascal также имеют `.pas`, но экспортируются отдельно. PlantUML и DOT сохраняются как редактируемые исходники; для рендеринга нужна PlantUML/Graphviz. Power Query сохраняет выбранное расширение `.pq` или `.m`. |
| DATA | JSON, JSONL, XML, YAML/YML, TOML, INI, CONF, ENV, Properties, CSV, TSV | Каждый блок выбранного формата — отдельным файлом. Если блоки CSV/TSV отсутствуют, Markdown-таблицы выгружаются по одной в отдельные CSV/TSV. |

Power Query распознаёт метки `m`, `pq`, `powerquery`, `power-query` и `power query`. Используйте fenced-метки `drawio`, `bpmn`, `puml`, `dot`, `eps` и `dxf` для соответствующих исходников. В меню PDF подписаны по назначению: DOC → «PDF документа (текст ответа)», IMG → «PDF рисунка из SVG (вектор)». Оба файла имеют расширение `.pdf`, но содержат разные материалы. CDR напрямую не создаётся: откройте SVG в CorelDRAW и сохраните оттуда. Для IMG браузер должен разрешить несколько загрузок; внутренние ссылки принимаются только с того же origin Open WebUI.

Экспорт и преобразования выполняются локально в браузере и не используют внешние библиотеки, CDN или интернет-сервисы. Установка обновляет только Open WebUI Functions; базовые Docker-образы и compose-файлы не меняются. PlantUML и Graphviz выгружаются исходным текстом: рендеринг схем этими программами не запускается.

## Сборка и проверки

Из корня проекта пересоберите пакет командой `python format-exporters-v2/build_all.py`. Unit-тесты запускаются из корня: `python -m unittest discover -s tests -p test_format_exporters_v2.py -v`. Готовые Actions автономны после сборки и не требуют соседних каталогов при установке.

## Установка и удаление

`./install-functions.sh` устанавливает/обновляет все четыре Function через API Open WebUI; `--img`, `--doc`, `--code`, `--data` выбирают классы. Удаление требует явного выбора, например `./remove-functions.sh --all` или `./remove-functions.sh --doc`. В API используются отдельные ID `export_*_menu_v2`: удаление этого пакета не удаляет старые экспортёры. Скрипты запрашивают e-mail администратора Open WebUI и скрыто читают его пароль; SSH-учётные данные не подходят для API.

Для ручного импорта доступны `functions.json` в корне и отдельные манифесты в каталогах классов. После сборки сохранённые в Open WebUI Actions обновляются запуском установщика.
'''
    (HERE / "README.md").write_text(package_readme.replace("{VERSION}", VERSION), encoding="utf-8", newline="\n")

    manager = (HERE / "manage-functions.py").read_text(encoding="utf-8")
    manager = re.sub(r'"images": \(.*?\),\n    "documents": \(.*?\),\n    "code": \(.*?\),\n    "data": \(.*?\),',
        '"images": ("export_images_menu_v2", "Экспорт изображений V2 (IMG)", "SVG, PDF рисунка, EPS, DXF, PNG/JPG/BMP/GIF/WebP локально в браузере."),\n'
        '    "documents": ("export_documents_menu_v2", "Экспорт документов V2 (DOC)", "DOCX/PPTX по одному файлу; PDF документа; XLSX, VSDX, Draw.io, BPMN, Markdown и TXT."),\n'
        '    "code": ("export_code_menu_v2", "Экспорт кода V2 (CODE)", "Исходники, включая PlantUML и Graphviz DOT."),\n'
        '    "data": ("export_data_menu_v2", "Экспорт данных V2 (DATA)", "Экспорт всех блоков выбранного формата."),', manager, flags=re.S)
    manager = re.sub(r'\d{4}\.\d{2}\.\d{2}\.\d+', VERSION, manager)
    (HERE / "manage-functions.py").write_text(manager, encoding="utf-8", newline="\n")
    for script in ("install-functions.sh", "remove-functions.sh"):
        path = HERE / script
        path.write_text(re.sub(r'(?<=SCRIPT_VERSION=")\d{4}\.\d{2}\.\d{2}\.\d+', VERSION, path.read_text(encoding="utf-8")), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    build()
