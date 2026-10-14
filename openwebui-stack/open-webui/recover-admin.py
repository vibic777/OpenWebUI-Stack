#!/usr/bin/env python3
"""Сброс пароля / роли админа Open WebUI без потери чатов и пользователей.

Нужен SSH на хост Docker. Не делает down -v, DELETE, DROP, volume rm.
Меняет только строку в таблицах auth и/или user.

  python3 recover-admin.py list
  python3 recover-admin.py password you@example.com
  python3 recover-admin.py promote you@example.com
  python3 recover-admin.py password you@example.com --promote

Документация: docs/auth.md и deploy/open-webui/README.md.
Тот же сброс без Python на хосте: recover-admin.sh (docker exec + psql).
"""
from __future__ import annotations

import argparse
import getpass
import os
import re
import subprocess
import sys
from pathlib import Path

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
CONTAINERS = {
    "postgres": "openwebui-postgres",
    "webui": "open-webui",
}


def die(msg: str, code: int = 1) -> None:
    print(msg, file=sys.stderr)
    raise SystemExit(code)


def find_compose_dir() -> Path:
    override = os.environ.get("COMPOSE_DIR") or os.environ.get("COMPOSE_ENV")
    if override:
        p = Path(override).expanduser().resolve()
        if p.is_file():
            p = p.parent
        if (p / ".env").is_file():
            return p
        die(f"COMPOSE_DIR/COMPOSE_ENV: нет .env в {p}")

    starts = [
        Path.cwd(),
        Path(__file__).resolve().parent,
        Path(__file__).resolve().parent.parent,
        Path(__file__).resolve().parent.parent.parent,
    ]
    seen: set[Path] = set()
    for start in starts:
        cur = start
        for _ in range(6):
            if cur in seen:
                break
            seen.add(cur)
            for cand in (cur, cur / "compose"):
                if (cand / "docker-compose.yml").is_file() and (cand / ".env").is_file():
                    return cand
            if cur.parent == cur:
                break
            cur = cur.parent
    die(
        "не найден docker-compose.yml + .env. Запустите из каталога стека "
        "или задайте COMPOSE_DIR=."
    )


def load_env(compose_dir: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    for raw in (compose_dir / ".env").read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        env[key.strip()] = val.strip().strip('"').strip("'")
    for key in ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB"):
        if not env.get(key):
            die(f"в .env нет {key}")
    return env


def docker_ok(name: str) -> None:
    p = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Running}}", name],
        capture_output=True,
        text=True,
    )
    if p.returncode != 0 or p.stdout.strip() != "true":
        die(f"контейнер {name} не запущен. Не используйте down -v — только up -d.")


def psql(env: dict[str, str], sql: str) -> str:
    p = subprocess.run(
        [
            "docker",
            "exec",
            "-e",
            f"PGPASSWORD={env['POSTGRES_PASSWORD']}",
            CONTAINERS["postgres"],
            "psql",
            "-U",
            env["POSTGRES_USER"],
            "-d",
            env["POSTGRES_DB"],
            "-v",
            "ON_ERROR_STOP=1",
            "-t",
            "-A",
            "-c",
            sql,
        ],
        capture_output=True,
        text=True,
    )
    if p.returncode != 0:
        die("psql:\n" + (p.stderr or p.stdout or "ошибка"))
    return p.stdout


def sql_str(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def check_email(email: str) -> str:
    email = email.strip().lower()
    if not EMAIL_RE.match(email):
        die("нужен обычный email, например admin@example.com")
    return email


def cmd_list(env: dict[str, str]) -> None:
    out = psql(
        env,
        """
        SELECT u.email || E'\\t' || COALESCE(u.role, '') || E'\\t' || COALESCE(a.active::text, '')
        FROM "user" u
        LEFT JOIN auth a ON a.id = u.id
        ORDER BY u.created_at;
        """,
    )
    print("email\trole\tauth_active")
    text = out.strip()
    if not text:
        print("(пользователей нет — регистрация первого даст админа; чаты не трогаем)")
        return
    print(text)


def hash_password(password: str) -> str:
    if len(password.encode("utf-8")) > 72:
        die("пароль длиннее 72 байт — bcrypt Open WebUI такой не примет")
    p = subprocess.run(
        [
            "docker",
            "exec",
            "-i",
            CONTAINERS["webui"],
            "python",
            "-c",
            "import sys,bcrypt; p=sys.stdin.buffer.read();"
            "print(bcrypt.hashpw(p, bcrypt.gensalt()).decode())",
        ],
        input=password.encode("utf-8"),
        capture_output=True,
    )
    if p.returncode != 0:
        die("не удалось посчитать хеш в контейнере open-webui:\n" + p.stderr.decode("utf-8", "replace"))
    return p.stdout.decode("utf-8").strip()


def cmd_password(env: dict[str, str], email: str, promote: bool) -> None:
    email = check_email(email)
    exists = psql(
        env,
        f"SELECT count(*) FROM auth WHERE lower(email) = lower({sql_str(email)});",
    ).strip()
    if exists != "1":
        die(
            f"в auth нет учётки {email}. Смотрите list. "
            "Нового человека так не создаём — только сброс существующего."
        )
    password = getpass.getpass("новый пароль (не отображается): ")
    if not password:
        die("пустой пароль нельзя")
    again = getpass.getpass("ещё раз: ")
    if password != again:
        die("пароли не совпали")
    hashed = hash_password(password)
    n = psql(
        env,
        f"UPDATE auth SET password = {sql_str(hashed)}, active = true "
        f"WHERE lower(email) = lower({sql_str(email)}) RETURNING email;",
    ).strip()
    if not n:
        die("UPDATE auth не затронул строк — ничего не удаляли, проверьте email")
    print(f"пароль обновлён для {n}. чаты и остальные пользователи без изменений.")
    if promote:
        cmd_promote(env, email)


def cmd_promote(env: dict[str, str], email: str) -> None:
    email = check_email(email)
    n = psql(
        env,
        f'UPDATE "user" SET role = {sql_str("admin")} '
        f"WHERE lower(email) = lower({sql_str(email)}) RETURNING email || E'\\t' || role;",
    ).strip()
    if not n:
        die(f"в \"user\" нет {email}. list покажет, кто есть. никого не удаляли.")
    print(f"роль admin: {n.replace(chr(9), ' / ')}")
    print("остальные пользователи и чаты на месте.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Вернуть админку Open WebUI по SSH. Чаты и пользователи сохраняются."
    )
    parser.add_argument(
        "action",
        choices=["list", "password", "promote"],
        help="list — кто есть; password — сброс пароля; promote — выдать роль admin",
    )
    parser.add_argument("email", nargs="?", help="email существующего пользователя")
    parser.add_argument(
        "--promote",
        action="store_true",
        help="вместе с password сразу выдать роль admin",
    )
    args = parser.parse_args()
    if args.action != "list" and not args.email:
        die("укажите email, см. сначала: recover-admin.py list")

    compose_dir = find_compose_dir()
    env = load_env(compose_dir)
    docker_ok(CONTAINERS["postgres"])
    if args.action == "password":
        docker_ok(CONTAINERS["webui"])

    print("каталог стека:", compose_dir)
    print("тома и пользователи не удаляются.\n")

    if args.action == "list":
        cmd_list(env)
    elif args.action == "password":
        cmd_password(env, args.email, args.promote)
    elif args.action == "promote":
        cmd_promote(env, args.email)


if __name__ == "__main__":
    main()
