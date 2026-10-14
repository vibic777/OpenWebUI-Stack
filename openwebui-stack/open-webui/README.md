# Lost Open WebUI admin password

SSH onto the Docker host. Chats, files, and other users stay.  
**Never** `down -v`, `volume rm`, `DELETE FROM "user"`, or recreate Postgres.

Passwords live in Postgres table `auth`. Role lives in `"user"`.  
Containers: `openwebui-postgres` (psql) and `open-webui` (bcrypt — the hash must match what the UI checks).

Run from the directory that contains the active stack `.env` and `docker-compose.yml`.  
Or `COMPOSE_DIR=/path/to/stack`.

## Shell (no Python on the host)

```bash
chmod +x open-webui/recover-admin.sh
./open-webui/recover-admin.sh list
./open-webui/recover-admin.sh password admin@example.com --promote
```

Same thing if you already copied `recover-admin.sh` next to compose.

## Python (optional)

```bash
python3 open-webui/recover-admin.py list
python3 open-webui/recover-admin.py password admin@example.com --promote
```

## Jump into the containers (copy-paste)

`psql` is already inside `openwebui-postgres`. You do **not** install Postgres on the host.

Load DB name/user/password from `.env` (do not paste the live password into chat/git):

```bash
set -a
. ./.env
set +a
```

**Who is in the DB** (no password hashes):

```bash
docker exec -e PGPASSWORD="$POSTGRES_PASSWORD" openwebui-postgres \
  psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c \
  'SELECT u.email, u.role, a.active FROM "user" u LEFT JOIN auth a ON a.id = u.id ORDER BY u.created_at;'
```

**Make a bcrypt hash** (inside Open WebUI, then paste the one-line `$2b$…` into the UPDATE):

```bash
docker exec -it open-webui python -c \
  'import getpass,bcrypt; p=getpass.getpass("new password: ").encode(); print(bcrypt.hashpw(p, bcrypt.gensalt()).decode())'
```

**Write the hash + keep the account active** (replace EMAIL and HASH; single quotes in HASH are doubled `'` → `''`):

```bash
docker exec -e PGPASSWORD="$POSTGRES_PASSWORD" -it openwebui-postgres \
  psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"
```

Inside `psql`:

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

`\q` to leave. Browser login on `/`. No container restart.

Do not `CREATE` a new user this way. If `list` is empty, that is an empty volume — first signup becomes admin; that is not a forgotten-password case.

## What not to do

- Do not delete volume `postgres_data`
- Do not `docker compose down -v`
- Do not `DROP TABLE` / wipe `"user"` “to be sure”
