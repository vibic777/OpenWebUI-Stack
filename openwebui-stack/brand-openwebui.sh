#!/usr/bin/env bash
# Temporarily set the Open WebUI sidebar name inside the current container.
set -euo pipefail

CONTAINER="open-webui"
DEFAULT_NAME="Open WebUI Stack"
TARGET_NAME="$DEFAULT_NAME"
ACTION="${1:-}"
CONFIRM=0

usage() {
  cat <<'HELP'
Временная замена имени Open WebUI в текущем контейнере.

Использование:
  ./brand-openwebui.sh apply [--name "имя"] [--yes]
  ./brand-openwebui.sh restore [--yes]
  ./brand-openwebui.sh status
  ./brand-openwebui.sh -h|--help

apply    По умолчанию задаёт «Open WebUI Stack»; --name позволяет указать
         другое имя. Затем перезапускает контейнер open-webui.
restore  Возвращает исходный env.py из резервной копии и перезапускает контейнер.
status   Показывает, применена ли временная замена.

Изменяется только файл backend/open_webui/env.py внутри существующего контейнера.
Compose, образ, БД, чаты и тома не меняются. После пересоздания/обновления
контейнера патч исчезнет; выполните apply снова. Скрипт работает офлайн и
меняет файл только при совпадении ожидаемого кода; для другой версии остановится.

apply/restore запрашивают подтверждение; введите y/да. --yes пропускает вопрос.
Пример: ./brand-openwebui.sh apply --name "Мой ИИ-сервис"
Проверяйте соответствие использования branding условиям лицензии Open WebUI;
скрипт сам не определяет число пользователей за последние 30 дней.
HELP
}

if [[ "$ACTION" == -h || "$ACTION" == --help || -z "$ACTION" ]]; then
  usage
  [[ -n "$ACTION" ]] && exit 0 || exit 2
fi

case "$ACTION" in
  apply|restore)
    shift
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --yes)
          CONFIRM=1
          shift
          ;;
        --name)
          if [[ "$ACTION" != apply || $# -lt 2 || -z "$2" ]]; then
            echo "ОШИБКА: --name требует непустое имя и применим только с apply." >&2
            exit 2
          fi
          TARGET_NAME="$2"
          shift 2
          ;;
        *)
          echo "ОШИБКА: неизвестный аргумент '$1'; используйте --help." >&2
          exit 2
          ;;
      esac
    done
    if [[ "$ACTION" == restore && "$TARGET_NAME" != "$DEFAULT_NAME" ]]; then
      echo "ОШИБКА: --name не применим с restore." >&2
      exit 2
    fi
    ;;
  status)
    shift
    if [[ $# -ne 0 ]]; then
      echo "ОШИБКА: status не принимает аргументы; используйте --help." >&2
      exit 2
    fi
    ;;
  *)
    echo "ОШИБКА: укажите apply, restore или status; справка: --help." >&2
    exit 2
    ;;
esac

DOCKER_BIN="$(command -v docker 2>/dev/null || true)"
if [[ -z "$DOCKER_BIN" ]]; then
  for candidate in /usr/bin/docker /usr/local/bin/docker; do
    if [[ -x "$candidate" ]]; then
      DOCKER_BIN="$candidate"
      break
    fi
  done
fi
if [[ -z "$DOCKER_BIN" ]]; then
  echo "ОШИБКА: docker не найден." >&2
  exit 1
fi
if ! "$DOCKER_BIN" inspect "$CONTAINER" >/dev/null 2>&1; then
  echo "ОШИБКА: контейнер $CONTAINER не найден. Запустите скрипт на хосте Open WebUI." >&2
  exit 1
fi
if [[ "$("$DOCKER_BIN" inspect -f '{{.State.Running}}' "$CONTAINER")" != true ]]; then
  echo "ОШИБКА: контейнер $CONTAINER не запущен." >&2
  exit 1
fi

if [[ "$ACTION" != status && $CONFIRM -eq 0 ]]; then
  if [[ "$ACTION" == apply ]]; then
    prompt="Временно заменить имя на «$TARGET_NAME» и перезапустить Open WebUI? [y/N] "
  else
    prompt="Восстановить исходное имя и перезапустить Open WebUI? [y/N] "
  fi
  read -r -p "$prompt" answer || answer=""
  case "${answer,,}" in
    y|yes|д|да) ;;
    *) echo "Отменено; контейнер не менялся."; exit 0 ;;
  esac
fi

"$DOCKER_BIN" exec -i -u 0 "$CONTAINER" python3 - "$ACTION" "$TARGET_NAME" <<'PY'
import os
import re
import ast
import shutil
import sys
import tempfile
from pathlib import Path

action, target_name = sys.argv[1:]
candidates = [Path("/app/backend/open_webui/env.py")]
source_path = next((path for path in candidates if path.is_file()), None)
if source_path is None:
    print("ОШИБКА: в контейнере не найден поддерживаемый backend/open_webui/env.py.", file=sys.stderr)
    raise SystemExit(1)

backup_path = source_path.with_name(source_path.name + ".openwebui-stack-brand-backup")
legacy_backups = sorted(source_path.parent.glob(source_path.name + ".*-brand-backup"))
source = source_path.read_text(encoding="utf-8")
stock_pattern = re.compile(
    r"(?m)^WEBUI_NAME = os\.getenv\('WEBUI_NAME', 'Open WebUI'\)\r?\n"
    r"(?:[ \t]*\r?\n)*"
    r"if WEBUI_NAME != 'Open WebUI':\r?\n"
    r"(?:[ \t]*\r?\n)*"
    r"[ \t]+WEBUI_NAME \+= ' \(Open WebUI\)'"
)
patched_pattern = re.compile(
    r"(?m)^WEBUI_NAME = os\.getenv\('WEBUI_NAME', 'Open WebUI'\)\r?\n"
    r"(?:[ \t]*\r?\n)*"
    r"if WEBUI_NAME != 'Open WebUI':\r?\n"
    r"(?:[ \t]*\r?\n)*"
    r"[ \t]+WEBUI_NAME = (?P<name>[^\r\n]+)"
)

def atomic_write(path: Path, content: str) -> None:
    metadata = path.stat()
    fd, temp_name = tempfile.mkstemp(prefix=".env.py-brand-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
            stream.write(content)
        os.chmod(temp_name, metadata.st_mode & 0o7777)
        os.chown(temp_name, metadata.st_uid, metadata.st_gid)
        os.replace(temp_name, path)
    except BaseException:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise

if action == "status":
    patched_match = patched_pattern.search(source)
    if patched_match:
        try:
            patched_name = ast.literal_eval(patched_match.group("name"))
        except (ValueError, SyntaxError):
            print("Состояние: временный блок найден, но имя не удалось прочитать.")
            raise SystemExit(2)
        effective_name = patched_name if os.getenv("WEBUI_NAME", "Open WebUI") != "Open WebUI" else "Open WebUI"
        state = "временное имя применено"
    elif stock_pattern.search(source):
        effective_name = os.getenv("WEBUI_NAME", "Open WebUI")
        if effective_name != "Open WebUI":
            effective_name += " (Open WebUI)"
        state = "штатный код Open WebUI"
    else:
        print(f"Состояние: неизвестный вариант branding; файл не менялся. Файл: {source_path}")
        raise SystemExit(2)
    print(f"Текущее имя: {effective_name}")
    print(f"Состояние: {state}. Файл: {source_path}")
elif action == "apply":
    patched_match = patched_pattern.search(source)
    if patched_match:
        try:
            patched_name = ast.literal_eval(patched_match.group("name"))
        except (ValueError, SyntaxError):
            print("ОШИБКА: временное имя не удалось безопасно разобрать; файл не менялся.", file=sys.stderr)
            raise SystemExit(2)
        if not isinstance(patched_name, str):
            print("ОШИБКА: блок branding содержит имя нестрокового типа; файл не менялся.", file=sys.stderr)
            raise SystemExit(2)
        if patched_name == target_name:
            print(f"Имя «{target_name}» уже задано в {source_path}; файл не менялся.")
        else:
            updated = patched_pattern.sub(
                "WEBUI_NAME = os.getenv('WEBUI_NAME', 'Open WebUI')\n"
                "if WEBUI_NAME != 'Open WebUI':\n"
                f"    WEBUI_NAME = {target_name!r}",
                source,
                count=1,
            )
            compile(updated, str(source_path), "exec")
            atomic_write(source_path, updated)
            print(f"Временное имя изменено на «{target_name}». Резервная копия: {backup_path}")
    else:
        match = stock_pattern.search(source)
        if not match:
            print("ОШИБКА: ожидаемый блок Open WebUI branding не найден; файл не менялся.", file=sys.stderr)
            raise SystemExit(2)
        updated = stock_pattern.sub(
            "WEBUI_NAME = os.getenv('WEBUI_NAME', 'Open WebUI')\n"
            "if WEBUI_NAME != 'Open WebUI':\n"
            f"    WEBUI_NAME = {target_name!r}",
            source,
            count=1,
        )
        compile(updated, str(source_path), "exec")
        if not backup_path.exists() and not legacy_backups:
            shutil.copy2(source_path, backup_path)
        atomic_write(source_path, updated)
        print(f"Временная замена имени применена. Резервная копия: {backup_path}")
elif action == "restore":
    restore_backup = backup_path
    if not restore_backup.exists() and len(legacy_backups) == 1:
        restore_backup = legacy_backups[0]
    if len(legacy_backups) > 1 and not backup_path.exists():
        print("ОШИБКА: найдено несколько старых резервных копий; восстановление отменено.", file=sys.stderr)
        raise SystemExit(2)
    if restore_backup.exists():
        shutil.copy2(restore_backup, source_path)
        restore_backup.unlink()
        print(f"Исходный файл восстановлен: {source_path}")
    elif stock_pattern.search(source):
        print("Штатное имя уже действует; файл не менялся.")
    else:
        print("ОШИБКА: резервная копия не найдена; автоматически восстановить исходник нельзя.", file=sys.stderr)
        raise SystemExit(2)
PY

if [[ "$ACTION" != status ]]; then
  echo "Перезапускаю $CONTAINER, чтобы новое имя загрузилось..."
  "$DOCKER_BIN" restart "$CONTAINER" >/dev/null
  echo "Готово. Контейнер перезапущен; возможна короткая недоступность интерфейса."
fi
