# Functions (plugins) for Open WebUI

These Functions use libraries already included in the Open WebUI image
(python-docx, openpyxl, python-pptx, fpdf2 + bundled Noto fonts, stdlib). No `requirements:`, no pip, no downloads.
The installer does not download Python packages. If a required library is missing from the image, the Function reports the missing module.

| File | Type | What it does |
|---|---|---|
| `export_office.py` | Action, **11 buttons** | assistant answer → **DOCX**, **XLSX**, **PPTX**, **VSDX**, **PDF**, **MD**, **TXT**, **CSV**, **SVG**, **PNG**, **JPG** |
| `token_and_time.py` | Filter | tokens in/out, total, seconds, tok/s and chat total under every reply |
| `message_timestamps.py` | Filter | date/time of every message always visible (not only on hover) |

Cyrillic, Latin and Chinese are supported (PDF uses the Noto fonts shipped in the image; DOCX/PPTX declare an East-Asian font).

## Install (offline)

Automatic (recommended), from the stack folder on the server:

```bash
cd openwebui-stack/open-webui
./install-functions.sh --email admin@example.com --ask-password
```

Remove: from the stack root, run `./open-webui/remove-functions.sh --all`.

Manual: Admin → **Functions** → **+ New** → paste the file → Save → switch **Active** and **Global** on.
After that every assistant message has buttons **DOCX / XLSX / PPTX / VSDX / PDF / MD / TXT / CSV / SVG / PNG / JPG** (hover the small icons under the message). Code/config exports are available in the separate `format-exporters/` and `format-exporters-v2/` packages.

Functions are stored in PostgreSQL: they are kept by `backup-stack.sh` / `restore-stack.sh` and survive
stack redeploys (same database). To update: copy the new `.py`, run the installer again.

## How to get a good result

| Want | Ask the model |
|---|---|
| XLSX | "Ответь **таблицей** markdown" — every table becomes a sheet; numbers become numbers |
| PPTX | "Сделай структуру презентации: заголовки `##` = слайды, под ними маркированные пункты" |
| VSDX | "Нарисуй схему процесса как **mermaid flowchart** (`flowchart TD`, узлы `A[Текст]`, ветвления `B{Вопрос?}`)" |
| TXT | any answer; Markdown styling is converted to readable plain text |
| CSV | Markdown tables → UTF-8 CSV with escaped commas and quotes; requires at least one table |
| SVG | one fenced `svg` block or SVG markup; active elements and external links are rejected |
| PNG / JPG | embedded base64 image data or an internal Open WebUI file; external URLs are not fetched |
| DOCX / PDF | any markdown answer: headings, lists, tables, code |

Valves (Admin → Functions → ⚙): `scope` = `last_message` (default; the message whose button you clicked) or `all_messages` (whole chat);
`pdf_font_dir` only if the fonts are not found automatically.

## Limits (honest)

- **VSDX** is written by hand as an OPC package (no Visio library exists offline). It is checked structurally and
  by Apache Tika, but **not validated in Microsoft Visio: connectors are lines with arrowheads, not "glued" to shapes;
  auto-layout is layered (top-down / left-right) and may need manual tidying. Only `flowchart` / `graph` mermaid is understood.
- TXT is UTF-8 plain text; basic Markdown formatting is removed, tables use tab-separated cells.
- PPTX: plain layout (title + text, tables split by 9 rows); no images/charts.
- Image export accepts embedded base64 (20 MiB limit) or same-origin Open WebUI file-route references. SVG is limited to 2 MiB and screened for active content/external resources. External URLs are never fetched.
- If a future Open WebUI image drops one of the libraries, the button shows a clear error naming the missing module.

Remove: Admin → Functions → ⋯ → Delete. Never `down -v`.
