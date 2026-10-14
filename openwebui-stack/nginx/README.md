# nginx configs (package already installed)

This folder contains Nginx configuration and a landing page, not an Nginx package. Install Nginx from the host OS, adapt the virtual host and TLS paths, then validate with `nginx -t` before reloading.

## Repo file → host path

| In `openwebui-stack/nginx/` | On the Open WebUI host |
|---|---|
| `openwebui.conf` | `/etc/nginx/sites-available/openwebui` + symlink `sites-enabled/openwebui` |
| `auth-admins.conf` | `/etc/nginx/snippets/auth-admins.conf` |
| `qdrant-apikey.conf.example` | copy to `qdrant-apikey.conf`, set the real key, then `/etc/nginx/snippets/qdrant-apikey.conf` |
| `admins.htpasswd.example` | format only. Live file: `htpasswd -B` → `/etc/nginx/admins.htpasswd` |
| `stack.html` | `/var/www/html/stack.html` |
| TLS | **not in git** — see [../FAQ.md](../FAQ.md) (option A or B) |

Remove any other `default_server` on `:80`/`:443`.

```bash
cd openwebui-stack/nginx

sudo cp openwebui.conf /etc/nginx/sites-available/openwebui
sudo ln -sf /etc/nginx/sites-available/openwebui /etc/nginx/sites-enabled/openwebui

sudo mkdir -p /etc/nginx/snippets
sudo cp auth-admins.conf /etc/nginx/snippets/auth-admins.conf

# live secrets (not the .example files):
sudo cp qdrant-apikey.conf.example /etc/nginx/snippets/qdrant-apikey.conf
# Edit the copied file and replace API_KEY_ChangeMe with QDRANT_API_KEY from .env.
sudo htpasswd -cB /etc/nginx/admins.htpasswd ADMIN_USER
# For additional users, run htpasswd -B without -c.
sudo chown root:www-data /etc/nginx/admins.htpasswd
sudo chmod 640 /etc/nginx/admins.htpasswd

sudo cp stack.html /var/www/html/stack.html
sudo nginx -t && sudo systemctl reload nginx
```

`qdrant-apikey.conf` must use the **same** string as `QDRANT_API_KEY` in `.env`.

## What the site does

| URL | Upstream | Login |
|---|---|---|
| `/` | `127.0.0.1:3000` Open WebUI | Open WebUI users |
| `/portainer/` | `127.0.0.1:9000` | Portainer users |
| `/qdrant/` | `127.0.0.1:6333` | nginx Basic + api-key header |
| `/filer/` | `127.0.0.1:8888` | nginx Basic |
| `/stack.html` | file | none |

No HTTP Basic on `/` or `/portainer/`. The template is not installed automatically. Check the active host config with `sudo ./nginx-upload-limit.sh get --probe-size 2m` from `openwebui-stack/`. Change it with `set SIZE`: backup, `nginx -t`, then reload. `full-test.sh` only runs the safe HTTP probe and does not change Nginx config. LLM: proxy timeout 3600s.

TLS certificate paths in `openwebui.conf` must match the files installed on the host. Example:

```
ssl_certificate     /etc/ssl/certs/openwebui.crt;
ssl_certificate_key /etc/ssl/private/openwebui.key;
```
