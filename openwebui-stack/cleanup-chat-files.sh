#!/usr/bin/env bash
# Preview/delete only files linked to chats and to no protected resource.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ "${1:-}" == -h || "${1:-}" == --help ]]; then
  cat <<'HELP'
cleanup-chat-files.sh — безопасная очистка старых файлов, прикреплённых только к чатам.

Параметры передаются в cleanup-chat-files.py:
  --older-than DAYS  минимальный срок бездействия в днях; для удаления обязателен
  --delete           удалить найденных кандидатов через API Open WebUI
  --yes              пропустить подтверждение; допустим только вместе с --delete
  --api-url URL      адрес API (по умолчанию OPENWEBUI_LOCAL_URL или http://127.0.0.1:3000)
  -h, --help         показать эту справку

Без --delete выполняется только предпросмотр. Удаляются только файлы с chat-связью
без связей с Knowledge, каналами, заметками, общим доступом или collection_name.
Сами чаты и история сообщений остаются. Удалённые вложения из чатов восстановить
можно только из резервной копии. При удалении нужен OPENWEBUI_API_KEY или ввод ключа.

Примеры:
  ./cleanup-chat-files.sh                         # список всех допустимых кандидатов
  ./cleanup-chat-files.sh --older-than 30         # только неактивные 30+ дней
  ./cleanup-chat-files.sh --delete --older-than 90 # запрос подтверждения перед удалением
HELP
  exit 0
fi
command -v python3 >/dev/null 2>&1 || { echo "ERROR: python3 is required" >&2; exit 1; }
exec python3 "$HERE/cleanup-chat-files.py" "$@"
