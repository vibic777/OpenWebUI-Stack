# Конфиги nginx (пакет уже установлен)

Русская копия [README.md](README.md).

Эта папка содержит конфиги и стартовую страницу, но не пакет nginx. Установите nginx средствами ОС, настройте виртуальный хост и пути TLS-сертификатов, затем проверьте конфигурацию через `nginx -t` перед reload.

## Файл в репо → путь на хосте

| В `openwebui-stack/nginx/` | На хосте Open WebUI |
|---|---|
| `openwebui.conf` | `/etc/nginx/sites-available/openwebui` + symlink `sites-enabled/openwebui` |
| `auth-admins.conf` | `/etc/nginx/snippets/auth-admins.conf` |
| `qdrant-apikey.conf.example` | скопировать в `qdrant-apikey.conf`, вписать ключ, затем `/etc/nginx/snippets/qdrant-apikey.conf` |
| `admins.htpasswd.example` | только формат. Живой файл: `htpasswd -B` → `/etc/nginx/admins.htpasswd` |
| `stack.html` | `/var/www/html/stack.html` |
| TLS | **не в git** — [../RU-FAQ.md](../RU-FAQ.md) (вариант A или B) |

Убрать чужой `default_server` на `:80`/`:443`.

```bash
cd openwebui-stack/nginx

sudo cp openwebui.conf /etc/nginx/sites-available/openwebui
sudo ln -sf /etc/nginx/sites-available/openwebui /etc/nginx/sites-enabled/openwebui

sudo mkdir -p /etc/nginx/snippets
sudo cp auth-admins.conf /etc/nginx/snippets/auth-admins.conf

# живые секреты (не .example):
sudo cp qdrant-apikey.conf.example /etc/nginx/snippets/qdrant-apikey.conf
# В скопированном файле замените API_KEY_ChangeMe на QDRANT_API_KEY из .env.
sudo htpasswd -cB /etc/nginx/admins.htpasswd ADMIN_USER
# Для следующих пользователей запускайте htpasswd -B без -c.
sudo chown root:www-data /etc/nginx/admins.htpasswd
sudo chmod 640 /etc/nginx/admins.htpasswd

sudo cp stack.html /var/www/html/stack.html
sudo nginx -t && sudo systemctl reload nginx
```

В `qdrant-apikey.conf` **та же** строка, что `QDRANT_API_KEY` в `.env`.

## Что делает сайт

| URL | Upstream | Логин |
|---|---|---|
| `/` | `127.0.0.1:3000` Open WebUI | пользователи Open WebUI |
| `/portainer/` | `127.0.0.1:9000` | пользователи Portainer |
| `/qdrant/` | `127.0.0.1:6333` | nginx Basic + заголовок api-key |
| `/filer/` | `127.0.0.1:8888` | nginx Basic |
| `/stack.html` | файл | нет |

На `/` и `/portainer/` HTTP Basic не ставить. Шаблон задаёт `client_max_body_size 100m`, но автоматически не устанавливается. Фактическое значение проверяйте командой `sudo ./nginx-upload-limit.sh get --probe-size 2m` из `openwebui-stack/`. Для изменения используйте `set SIZE`: резервная копия, `nginx -t`, затем reload. `full-test.sh` выполняет только безопасную HTTP-пробу без изменения конфигурации. LLM: таймаут прокси 3600 с.

Пути TLS-сертификата и ключа в `openwebui.conf` должны соответствовать файлам на хосте. Пример:

```
ssl_certificate     /etc/ssl/certs/openwebui.crt;
ssl_certificate_key /etc/ssl/private/openwebui.key;
```
