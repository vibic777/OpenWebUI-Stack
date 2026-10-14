#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cat <<'HELP'
Экспорт всего чата для Open WebUI

Назначение:
  Экспортирует историю текущей ветки чата в один файл выбранного формата:
  DOCX, PPTX, XLSX, Markdown, TXT или JSON.
  В XLSX каждая Markdown-таблица помещается на отдельный лист.

Установка / обновление:
  bash install-functions.sh [--url URL] [--email ADMIN_EMAIL] [--container NAME]

Удаление только этой функции:
  bash remove-functions.sh --all [--url URL] [--email ADMIN_EMAIL] [--container NAME]

Сборка после изменения шаблона:
  python3 build.py

Параметры:
  --url URL             URL Open WebUI API внутри контейнера (по умолчанию
                        http://127.0.0.1:8080; также задаётся OWUI_URL)
  --email EMAIL         E-mail администратора Open WebUI; также OWUI_ADMIN_EMAIL
  --container NAME      Имя Docker-контейнера (по умолчанию open-webui)
  --all                 Обязательное подтверждение удаления единственной функции
  --help                Показать параметры конкретного скрипта
  --version             Показать версию установщика/удалятеля

Если e-mail не задан, скрипт запросит его. Пароль администратора вводится
скрыто в терминале и не сохраняется. SSH-учётные данные не подходят для API.
API-установщик находится в functions/install_functions.py. Функция Open WebUI
имеет ID export_entire_chat. Удалятор адресует только этот ID.
HELP
