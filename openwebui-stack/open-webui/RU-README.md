# Забыли пароль админа Open WebUI

Русская копия [README.md](README.md).

SSH на хост Docker. Чаты, файлы и остальные пользователи остаются.  
**Никогда** `down -v`, `volume rm`, `DELETE FROM "user"`, не пересоздавать Postgres.

Пароли в таблице Postgres `auth`. Роль — в `"user"`.  
Контейнеры: `openwebui-postgres` (`psql`) и `open-webui` (bcrypt — хеш должен совпасть с тем, что проверяет UI).

Запускайте из каталога активного стека, где находятся `.env` и `docker-compose.yml`.  
Либо `COMPOSE_DIR=/path/to/stack`.

## Шелл (Python на хосте не нужен)

```bash
chmod +x open-webui/recover-admin.sh
./open-webui/recover-admin.sh list
./open-webui/recover-admin.sh password admin@example.com --promote
```

То же, если `recover-admin.sh` уже лежит рядом с compose.

## Python (по желанию)

```bash
python3 open-webui/recover-admin.py list
python3 open-webui/recover-admin.py password admin@example.com --promote
```

## Зайти в контейнеры (копипаст)

`psql` уже **внутри** `openwebui-postgres`. Postgres на хост не ставить.

Имя БД / пользователь / пароль из `.env` (живой пароль в чат/git не копировать):

```bash
set -a
. ./.env
set +a
```

**Кто в БД** (без хешей паролей):

```bash
docker exec -e PGPASSWORD="$POSTGRES_PASSWORD" openwebui-postgres \
  psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c \
  'SELECT u.email, u.role, a.active FROM "user" u LEFT JOIN auth a ON a.id = u.id ORDER BY u.created_at;'
```

**Сделать bcrypt-хеш** (внутри Open WebUI, однострочный `$2b$…` вставить в UPDATE):

```bash
docker exec -it open-webui python -c \
  'import getpass,bcrypt; p=getpass.getpass("new password: ").encode(); print(bcrypt.hashpw(p, bcrypt.gensalt()).decode())'
```

**Записать хеш и оставить учётку активной** (EMAIL и HASH; одинарные кавычки в HASH удваивать `'` → `''`):

```bash
docker exec -e PGPASSWORD="$POSTGRES_PASSWORD" -it openwebui-postgres \
  psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"
```

Внутри `psql`:

```sql
UPDATE auth
SET password = 'PASTE_BCRYPT_HASH_HERE',
    active = true
WHERE lower(email) = lower('admin@example.com')
RETURNING email;

UPDATE "user"
SET role = 'admin'
WHERE lower(email) = lower('admin@example.com')
RETURNING email, role;
```

`\q` — выход. Вход в браузере на `/`. Рестарт контейнера не нужен.

Так **не** `CREATE` нового пользователя. Пустой `list` — пустой том; первый signup снова станет админом, это не «забыли пароль».

## Нельзя

- Удалять том `postgres_data`
- `docker compose down -v`
- `DROP TABLE` / чистить `"user"` «на всякий случай»
