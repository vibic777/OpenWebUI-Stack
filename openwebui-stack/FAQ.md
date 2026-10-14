# Mini FAQ — parameters, TLS, login

## What talks to what

```
Browser  --HTTPS :443-->  nginx (OS package, not Docker)
                              |
                              +-- /            --> 127.0.0.1:3000  Open WebUI (its own login)
                              +-- /portainer/  --> 127.0.0.1:9000  Portainer (its own login)
                              +-- /qdrant/     --> 127.0.0.1:6333  nginx Basic + Qdrant api-key header
                              +-- /filer/      --> 127.0.0.1:8888  nginx Basic
                              +-- /stack.html  --> file on disk

Open WebUI (Docker network `backend`)
  --> Postgres :5432
  --> Qdrant :6333  (QDRANT_API_KEY)
  --> Valkey :6379
  --> SeaweedFS S3 :8333  (S3 keys = s3.json)
  --> LM Studio host :1234/v1  (chat + embeddings)  HTTP inside the site, no TLS required
  --> (optional) llama.cpp rerank  openwebui-rerank:8080/v1/rerank
      internal Docker net only; no host port
```

Do not put Open WebUI under `/openwebui/` (SPA loads `/_app` and `/api` from `/`).

Run `./deploy-stack.sh --init` to create `.env` from the root `.env.example` with generated local secrets and a matching `seaweedfs/s3.json`. Edit host-specific values locally. Do not publish `.env` or runtime configuration files.

## `.env` parameters

| Variable | Meaning |
|---|---|
| `WEBUI_URL` | Public URL as in the browser (`https://host`). Also Portainer `--trusted-origins` |
| `POSTGRES_*` | DB name/user/password |
| `S3_BUCKET_NAME` / `S3_ACCESS_KEY` / `S3_SECRET_KEY` | Must match `s3.json` identities |
| `QDRANT_API_KEY` | Same value in Qdrant, Open WebUI, and nginx `qdrant-apikey.conf` |
| `LMSTUDIO_URL` | `http://<inference-host>:1234/v1` |
| `LMSTUDIO_API_KEY` | Bearer for LM Studio |
| `EMBEDDING_MODEL` | Example: `text-embedding-bge-m3` (dim 1024). Changing size = reindex, not `down -v` |
| `RERANK_*` | Optional comments only. Rerank is a **separate** compose, not required |

Also in compose (not always in `.env`): `ENABLE_PERSISTENT_CONFIG=false` so Documents/Tika URL come from YAML, not old Postgres. `CONTENT_EXTRACTION_ENGINE=tika` and `TIKA_SERVER_URL=http://openwebui-tika:9998`.

## Certificates (files are **not** in git)

nginx on the **Open WebUI host** only. The LM Studio host does not need these certs.

**Option A** (paths currently set in the shipped `openwebui.conf`; change them to match your host):

| Role | Path |
|---|---|
| server cert (or full chain) | `/etc/ssl/certs/openwebui.crt` |
| private key | `/etc/ssl/private/openwebui.key` |
| site CA (browsers, optional) | `/etc/ssl/openwebui/ca.crt` |

```
ssl_certificate     /etc/ssl/certs/openwebui.crt;
ssl_certificate_key /etc/ssl/private/openwebui.key;
```

**Option B** (one directory, better on a new VM — change two lines in the conf):

| Role | Path |
|---|---|
| CA for people to import | `/etc/ssl/openwebui/ca.crt` |
| server cert | `/etc/ssl/openwebui/server.crt` |
| key | `/etc/ssl/openwebui/server.key` |
| full chain | `/etc/ssl/openwebui/server-fullchain.crt` |

```
ssl_certificate     /etc/ssl/openwebui/server-fullchain.crt;
ssl_certificate_key /etc/ssl/openwebui/server.key;
```

SAN must include the DNS **and** IP users type in `WEBUI_URL`. Key mode `640`, owner `root:www-data` (Debian/Astra) or `root:nginx` (RHEL). Then `nginx -t && systemctl reload nginx`.

Minimal self-signed (browser warning):

```bash
sudo mkdir -p /etc/ssl/openwebui
sudo openssl req -x509 -nodes -newkey rsa:2048 -days 825 \
  -keyout /etc/ssl/openwebui/server.key \
  -out /etc/ssl/openwebui/server.crt \
  -subj "/CN=$(hostname)" \
  -addext "subjectAltName=DNS:$(hostname),IP:127.0.0.1"
```

Add the real VM IP/DNS to SAN. Import **`ca.crt`**, not `server.crt`, into Windows trusted roots / Firefox.

## Authentication (three separate circles)

| URL | Who | Where accounts live | How to revoke |
|---|---|---|---|
| `/` | chat users | Open WebUI → Postgres | Open WebUI admin UI. Lost admin password: `open-webui/recover-admin.sh` (or `.py`, or `docker exec` + `psql`) — **do not** delete volumes |
| `/portainer/` | Docker admins | Portainer itself | Portainer UI |
| `/qdrant/` and `/filer/` | storage consoles | `/etc/nginx/admins.htpasswd` | delete the line, copy file, `nginx reload` |
| Qdrant API / S3 | services, not people | `.env` + `s3.json` | rotate keys, recreate those containers |

Do **not** put HTTP Basic on `/` or `/portainer/` (double login / WebSocket pain).

Add another console admin without `-c` (which would overwrite existing users):

```bash
sudo htpasswd -B /etc/nginx/admins.htpasswd ANOTHER_USER
```

`qdrant-apikey.conf` must use the **same** string as `QDRANT_API_KEY`. nginx adds `api-key` after Basic; humans do not type the Qdrant key.

## Install nginx **configs** (nginx is already the OS package)

Do not apt/yum nginx from this folder. Copy files from `openwebui-stack/nginx/`:

```bash
cd openwebui-stack/nginx
sudo mkdir -p /etc/nginx/snippets
sudo cp openwebui.conf /etc/nginx/sites-available/openwebui
sudo ln -sf /etc/nginx/sites-available/openwebui /etc/nginx/sites-enabled/openwebui
sudo cp auth-admins.conf /etc/nginx/snippets/auth-admins.conf
sudo cp qdrant-apikey.conf.example /etc/nginx/snippets/qdrant-apikey.conf
# Edit the copied file and replace API_KEY_ChangeMe with QDRANT_API_KEY from .env.
sudo htpasswd -cB /etc/nginx/admins.htpasswd ADMIN_USER
sudo chown root:www-data /etc/nginx/admins.htpasswd
sudo chmod 640 /etc/nginx/admins.htpasswd
sudo cp stack.html /var/www/html/stack.html
sudo nginx -t && sudo systemctl reload nginx
```

Remove any other `default_server` on `:80`/`:443`. The checked-in template uses `client_max_body_size 100m`; uploads larger than the configured limit get **413**. The template value is not installed automatically; inspect the active host config and test the upload route with `sudo ./nginx-upload-limit.sh get --probe-size 2m` from `openwebui-stack/`. To change it, use `sudo ./nginx-upload-limit.sh set 100m`: backup → `nginx -t` → reload on success. `full-test.sh` only runs the read-only probe; it never edits/reloads nginx. Proxy timeouts 3600s are for long LLM replies.

## Temporary sidebar name

To inspect, temporarily set, or restore the Open WebUI sidebar name, use `./brand-openwebui.sh status|apply|restore` from this directory. `apply` and `restore` restart only the `open-webui` container and change only its `env.py`; they do not touch Compose, Postgres, chat data, or volumes. Reapply after recreating/updating the container. The helper refuses to patch an unrecognized upstream code block.

## Do not publish on the LAN

Postgres `:5432`, Valkey `:6379`, Qdrant gRPC `:6334`, Seaweed S3 `:8333`, Open WebUI `:3000`, Portainer `:9000`, rerank `:8080` (container only). Only nginx 80/443.

## Rerank on/off

Not in the default `docker-compose.yml`. Commands: [START.md](START.md). To drop it: `docker compose up -d` then `docker compose -f docker-compose.rerank.yml down` (no `-v`). Do not leave Open WebUI on the overlay if the rerank container is gone.

## Files in SeaweedFS (do not wipe the volume)

Uploading the **same** file twice stores **two** objects (new UUID each time). No content-hash dedup.

| Goal | Do this | Do not |
|---|---|---|
| Remove one Knowledge file | Workspace → Knowledge → that collection → delete **that** file in Open WebUI | Delete objects in `/filer/` |
| Drop a whole collection | Delete the Knowledge in Open WebUI (files may remain if still in chats) | `volume rm seaweedfs_data` |
| See disk use | `docker system df -v` / `df -h` on the VM; Filer `/filer/` is a **view**, nginx Basic | `down -v` |
| Chat attachment leftover | Files in Open WebUI (user/admin), not Filer | Hand-edit S3 keys in Filer |

Filer is for looking. Targeted delete goes through Open WebUI so Postgres + Qdrant stay in sync. After UI delete, SeaweedFS should shrink that object; leftover local `uploads/` in `openwebui_data` is a cache.

When to act: VM disk (often `/var`) heading to full — not “Filer has files”. First check unused Docker **images**, then duplicate Knowledge uploads.

## Volumes

Never `docker compose down -v` or `volume rm`. Names stay `postgres_data`, `qdrant_storage`, `valkey_data`, `seaweedfs_data`, `openwebui_data`, `portainer_data`.
