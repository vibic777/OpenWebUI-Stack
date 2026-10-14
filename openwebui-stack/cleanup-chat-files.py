#!/usr/bin/env python3
"""Preview or remove files linked only to saved chats, using Open WebUI's API."""
from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENV_FILE = HERE / ".env"


def read_env(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    if not path.is_file():
        return result
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key.strip()] = value.strip().strip("\"'")
    return result


SQL = r"""
WITH chat_usage AS (
    SELECT file_id, COUNT(DISTINCT chat_id) AS linked_chats, MAX(updated_at) AS last_chat_activity
    FROM chat_file
    GROUP BY file_id
), per_file AS (
    SELECT
        f.id,
        COALESCE(f.filename, f.meta->>'name', '(без имени)') AS filename,
        f.user_id,
        CASE WHEN f.meta->>'size' ~ '^[0-9]+$' THEN (f.meta->>'size')::bigint ELSE 0 END AS size_bytes,
        GREATEST(
            COALESCE(f.created_at, 0),
            COALESCE(f.updated_at, 0),
            COALESCE(c.last_chat_activity, 0)
        ) AS last_activity,
        c.linked_chats,
        EXISTS (SELECT 1 FROM knowledge_file kf WHERE kf.file_id = f.id) AS in_knowledge,
        EXISTS (SELECT 1 FROM channel_file chf WHERE chf.file_id = f.id) AS in_channel,
        EXISTS (
            SELECT 1 FROM note n
            WHERE CAST(n.data AS text) LIKE '%' || f.id || '%'
        ) AS in_note,
        EXISTS (
            SELECT 1 FROM access_grant ag
            WHERE ag.resource_type = 'file' AND ag.resource_id = f.id
        ) AS shared_file,
        NULLIF(f.meta->>'collection_name', '') IS NOT NULL AS has_collection
    FROM file f
    JOIN chat_usage c ON c.file_id = f.id
)
SELECT COALESCE(json_agg(to_jsonb(candidate) ORDER BY last_activity, id), '[]'::json)::text
FROM (
    SELECT * FROM per_file
    WHERE NOT in_knowledge AND NOT in_channel AND NOT in_note
      AND NOT shared_file AND NOT has_collection
      AND last_activity <= EXTRACT(EPOCH FROM NOW())::bigint - (@@DAYS@@ * 86400)
) AS candidate;
"""

SUMMARY_SQL = r"""
SELECT json_build_object(
    'files_total', (SELECT count(*) FROM file),
    'chat_linked', (SELECT count(DISTINCT file_id) FROM chat_file),
    'knowledge_linked', (SELECT count(DISTINCT file_id) FROM knowledge_file),
    'channel_linked', (SELECT count(DISTINCT file_id) FROM channel_file),
    'knowledge_bases', (SELECT count(*) FROM knowledge),
    'chats', (SELECT count(*) FROM chat)
)::text;
"""


def psql_query(sql: str, params: list[str], env: dict[str, str]) -> str:
    db_name = os.environ.get("POSTGRES_DB", env.get("POSTGRES_DB", "openwebui"))
    db_user = os.environ.get("POSTGRES_USER", env.get("POSTGRES_USER", "openwebui"))
    db_pass = os.environ.get("POSTGRES_PASSWORD", env.get("POSTGRES_PASSWORD", ""))
    if not db_pass:
        raise RuntimeError("POSTGRES_PASSWORD не задан в .env")
    process_env = os.environ.copy()
    process_env["PGPASSWORD"] = db_pass
    command = ["docker", "exec", "-i", "-e", "PGPASSWORD", "openwebui-postgres",
               "psql", "-X", "-qAt", "-v", "ON_ERROR_STOP=1", "-U", db_user, "-d", db_name]
    query = sql.replace("@@DAYS@@", str(int(params[0]))) if params else sql
    completed = subprocess.run(command + ["-c", query], env=process_env, text=True,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if completed.returncode:
        raise RuntimeError("Ошибка чтения связей файлов в PostgreSQL: " + completed.stderr.strip())
    return completed.stdout.strip()


def request_delete(api_url: str, token: str, file_id: str) -> tuple[int, str]:
    request = urllib.request.Request(
        api_url.rstrip("/") + "/api/v1/files/" + urllib.parse.quote(file_id, safe=""),
        method="DELETE",
        headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Безопасный предпросмотр или удаление старых файлов, связанных только с чатами.",
        epilog=("Примеры:\n"
                "  cleanup-chat-files.py\n"
                "  cleanup-chat-files.py --older-than 30\n"
                "  cleanup-chat-files.py --delete --older-than 90\n\n"
                "Без --delete данные не меняются. Перед удалением сначала проверьте предпросмотр.\n"
                "Knowledge, каналы, заметки, общие файлы и коллекции защищены проверкой связей."),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--older-than", type=int, default=0, metavar="DAYS",
                        help="учитывать только файлы без активности указанное число дней; при удалении обязательно")
    parser.add_argument("--delete", action="store_true", help="удалить только кандидаты из предпросмотра через Open WebUI API")
    parser.add_argument("--yes", action="store_true", help="пропустить подтверждение фразой; действует только вместе с --delete")
    parser.add_argument("--api-url", default=os.environ.get("OPENWEBUI_LOCAL_URL", "http://127.0.0.1:3000"),
                        help="базовый URL Open WebUI API (по умолчанию OPENWEBUI_LOCAL_URL или %(default)s)")
    args = parser.parse_args()
    if args.older_than < 0:
        parser.error("--older-than должен быть неотрицательным числом")
    if args.delete and args.older_than < 1:
        parser.error("для удаления укажите retention-порог: --delete --older-than DAYS (не менее 1)")
    if args.yes and not args.delete:
        parser.error("--yes имеет смысл только вместе с --delete")

    env = read_env(ENV_FILE)
    try:
        summary = json.loads(psql_query(SUMMARY_SQL, [], env))
        candidates = json.loads(psql_query(SQL, [str(args.older_than)], env) or "[]")
    except Exception as exc:
        print(f"ОШИБКА: {exc}", file=sys.stderr)
        return 1

    print("Open WebUI — безопасная очистка только chat-linked файлов")
    print("Данные чатов и Knowledge-векторы/файлы не выбираются для удаления.")
    print("Сводка БД: " + ", ".join(f"{key}={value}" for key, value in summary.items()))
    print(f"Возрастной порог: {args.older_than} дн.; кандидатов: {len(candidates)}")
    if not candidates:
        print("Нечего очищать.")
        return 0

    total_bytes = sum(int(item.get("size_bytes") or 0) for item in candidates)
    for item in candidates:
        age = max(0, int((time.time() - int(item["last_activity"])) // 86400))
        print(f"- id={item['id']} | chats={item['linked_chats']} | age={age} дн. | "
              f"size={int(item.get('size_bytes') or 0)} B | {item['filename']}")
    print(f"Итого к освобождению по метаданным: {total_bytes} B")
    if not args.delete:
        print("Режим предпросмотра: ничего не удалено. Для очистки повторите команду с --delete --older-than DAYS.")
        return 0

    token = os.environ.get("OPENWEBUI_API_KEY", "").strip()
    if not token:
        token = getpass.getpass("Open WebUI admin API key: ").strip()
    if not token:
        print("ОШИБКА: нужен admin API key Open WebUI.", file=sys.stderr)
        return 1
    if not args.yes:
        phrase = f"delete {len(candidates)} chat files"
        answer = input(f"Убедитесь, что сейчас никто не добавляет файлы в Knowledge. Для продолжения введите точно: {phrase}\n> ")
        if answer != phrase:
            print("Отменено; ничего не удалено.")
            return 1

    deleted = failed = 0
    for item in candidates:
        # Refresh classification before each API delete to skip files that became linked elsewhere.
        try:
            current = json.loads(psql_query(SQL, [str(args.older_than)], env) or "[]")
        except Exception as exc:
            print(f"STOP: повторная проверка связей не удалась: {exc}", file=sys.stderr)
            return 1
        if not any(current_item["id"] == item["id"] for current_item in current):
            print(f"SKIP  {item['id']}: появился новый/защищённый тип связи или изменился возраст")
            continue
        status, body = request_delete(args.api_url, token, item["id"])
        if status == 200:
            deleted += 1
            print(f"PASS  {item['id']}: удалён через Open WebUI API (DB, SeaweedFS и file-collection)")
        else:
            failed += 1
            print(f"FAIL  {item['id']}: HTTP {status}; {body[:240]}")

    print(f"Итог: удалено={deleted}, ошибок={failed}. Knowledge-коллекции не удалялись.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
