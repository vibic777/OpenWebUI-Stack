# Экспорт документов

Отдельный Action с меню DOCX, XLSX, PPTX, VSDX, PDF, Markdown и TXT. Зависит только от библиотек, уже имеющихся в образе Open WebUI; контейнер и сеть не нужны для установки. XLSX ожидает Markdown-таблицу.

Установка: `sudo ./install-functions.sh` (или `--email ADMIN_EMAIL`). Удаление только этого Action: `sudo ./remove-functions.sh`.

Для DOCX/PDF/PPTX/TXT/Markdown дайте структурированный ответ с заголовками, списком и абзацем; для XLSX добавьте Markdown-таблицу. Для VSDX используйте Mermaid `flowchart TD` или `flowchart LR` с простыми узлами и `-->`. После скачивания откройте `.vsdx` в Visio и проверьте раскладку.
