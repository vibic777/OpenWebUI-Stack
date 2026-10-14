# Мини-FAQ — параметры, TLS, логины

Русская копия [FAQ.md](FAQ.md).

## Кто с кем говорит

```
Браузер  --HTTPS :443-->  nginx (пакет ОС, не Docker)
                              |
                              +-- /            --> 127.0.0.1:3000  Open WebUI (свой логин)
                              +-- /portainer/  --> 127.0.0.1:9000  Portainer (свой логин)
                              +-- /qdrant/     --> 127.0.0.1:6333  nginx Basic + заголовок api-key Qdrant
                              +-- /filer/      --> 127.0.0.1:8888  nginx Basic
                              +-- /stack.html  --> файл на диске

Open WebUI (сеть Docker `backend`)
  --> Postgres :5432
  --> Qdrant :6333  (QDRANT_API_KEY)
  --> Valkey :6379
  --> SeaweedFS S3 :8333  (ключи S3 = s3.json)
  --> хост LM Studio :1234/v1  (чат + эмбеддинги)  HTTP внутри площадки, TLS не обязателен
  --> (по желанию) llama.cpp rerank  openwebui-rerank:8080/v1/rerank
      только внутренняя сеть Docker; порта на хост нет
```

Open WebUI нельзя сажать в `/openwebui/` (SPA грузит `/_app` и `/api` с корня).

Запустить `./deploy-stack.sh --init`: команда создаст `.env` из корневого `.env.example`, сгенерирует локальные секреты и согласованный `seaweedfs/s3.json`. Параметры хоста задать локально. Не публиковать заполненный `.env` и runtime-конфиги.

## Параметры `.env`

| Переменная | Смысл |
|---|---|
| `WEBUI_URL` | Публичный URL как в браузере (`https://хост`). Ещё Portainer `--trusted-origins` |
| `POSTGRES_*` | Имя БД / пользователь / пароль |
| `S3_BUCKET_NAME` / `S3_ACCESS_KEY` / `S3_SECRET_KEY` | Должны совпасть с identities в `s3.json` |
| `QDRANT_API_KEY` | То же в Qdrant, Open WebUI и nginx `qdrant-apikey.conf` |
| `LMSTUDIO_URL` | `http://<хост-инференса>:1234/v1` |
| `LMSTUDIO_API_KEY` | Bearer для LM Studio |
| `EMBEDDING_MODEL` | Пример: `text-embedding-bge-m3` (dim 1024). Смена размерности = переиндекс, не `down -v` |
| `RERANK_*` | Только комментарии. Реранк — **отдельный** compose, не обязателен |

Ещё в compose (не всегда в `.env`): `ENABLE_PERSISTENT_CONFIG=false`, чтобы URL Documents/Tika брался из YAML, не из старого Postgres. `CONTENT_EXTRACTION_ENGINE=tika` и `TIKA_SERVER_URL=http://openwebui-tika:9998`.

## Сертификаты (файлов **нет** в git)

nginx только на **хосте Open WebUI**. Хосту LM Studio эти certs не нужны.

**Вариант A** (пути, указанные в `openwebui.conf`; измените их под свой хост):

| Роль | Путь |
|---|---|
| серверный cert (или полная цепочка) | `/etc/ssl/certs/openwebui.crt` |
| ключ | `/etc/ssl/private/openwebui.key` |
| CA площадки (браузеры, по желанию) | `/etc/ssl/openwebui/ca.crt` |

```
ssl_certificate     /etc/ssl/certs/openwebui.crt;
ssl_certificate_key /etc/ssl/private/openwebui.key;
```

**Вариант B** (один каталог, удобнее на новой ВМ — две строки в conf):

| Роль | Путь |
|---|---|
| CA людям в доверенные | `/etc/ssl/openwebui/ca.crt` |
| серверный cert | `/etc/ssl/openwebui/server.crt` |
| ключ | `/etc/ssl/openwebui/server.key` |
| полная цепочка | `/etc/ssl/openwebui/server-fullchain.crt` |

```
ssl_certificate     /etc/ssl/openwebui/server-fullchain.crt;
ssl_certificate_key /etc/ssl/openwebui/server.key;
```

В SAN — DNS **и** IP, которые люди пишут в `WEBUI_URL`. Ключ `640`, владелец `root:www-data` (Debian/Astra) или `root:nginx` (RHEL). Потом `nginx -t && systemctl reload nginx`.

Минимум самоподписанный (браузер ругается): те же команды `openssl`, что в [FAQ.md](FAQ.md). В доверенные корни Windows / Firefox импортировать **`ca.crt`**, не `server.crt`.

## Аутентификация (три независимых круга)

| URL | Кто | Где учётки | Как отозвать |
|---|---|---|---|
| `/` | чат | Open WebUI → Postgres | админка Open WebUI. Забыли пароль: `open-webui/recover-admin.sh` — **тома не удалять** |
| `/portainer/` | админы Docker | сам Portainer | UI Portainer |
| `/qdrant/` и `/filer/` | консоли хранилищ | `/etc/nginx/admins.htpasswd` | строка из файла, `nginx reload` |
| API Qdrant / S3 | сервисы, не люди | `.env` + `s3.json` | сменить ключи, пересоздать эти контейнеры |

**Не** вешать HTTP Basic на `/` и `/portainer/` (двойной логин / WebSocket).

Добавление ещё одного консольного администратора (без `-c`, чтобы не перезаписать существующих):

```bash
sudo htpasswd -B /etc/nginx/admins.htpasswd ANOTHER_USER
```

Создайте первый файл администраторов командой `sudo htpasswd -cB /etc/nginx/admins.htpasswd ADMIN_USER`; добавляйте следующих пользователей без флага `-c`, иначе файл будет перезаписан.

В `qdrant-apikey.conf` **та же** строка, что `QDRANT_API_KEY`. nginx подставляет `api-key` после Basic; люди ключ Qdrant не вводят.

## Поставить конфиги nginx (пакет уже есть)

Не apt/yum nginx из этой папки. Копировать из `openwebui-stack/nginx/` — команды как в [FAQ.md](FAQ.md) / [nginx/RU-README.md](nginx/RU-README.md).

Убрать чужой `default_server` на `:80`/`:443`. В шаблоне проекта задан `client_max_body_size 100m`; файлы больше фактического лимита дают **413**. Шаблон не развёртывает конфигурацию автоматически. Проверить активное значение и маршрут можно командой: `sudo ./nginx-upload-limit.sh get --probe-size 2m` из `openwebui-stack/`. Изменение: `sudo ./nginx-upload-limit.sh set 100m` — копия → `nginx -t` → reload после успеха. `full-test.sh` запускает только read-only пробу; конфиг не меняет и nginx не перезагружает. Таймауты прокси 3600 с — длинные ответы LLM.

## Временное имя в боковой панели

Проверить текущее имя, временно задать своё через `./brand-openwebui.sh apply --name "Название"` или вернуть исходное можно командами `./brand-openwebui.sh status|apply|restore`. Скрипт перезапускает только контейнер `open-webui` и меняет его `env.py`; Compose, Postgres, чаты и тома не затрагиваются. После пересоздания или обновления контейнера примените патч снова. Если upstream-код не совпадает с ожидаемым, скрипт откажется его менять.

## В LAN не публиковать

Postgres `:5432`, Valkey `:6379`, Qdrant gRPC `:6334`, Seaweed S3 `:8333`, Open WebUI `:3000`, Portainer `:9000`, rerank `:8080` (только контейнер). Снаружи только nginx 80/443.

## Реранк вкл/выкл

Не в основном `docker-compose.yml`. Команды: [RU-START.md](RU-START.md). Снять: `docker compose up -d` затем `docker compose -f docker-compose.rerank.yml down` (без `-v`). Не оставлять Open WebUI на оверлее, если контейнера реранка уже нет.

## Файлы в SeaweedFS (том не сносить)

Один и тот же файл второй раз → **два** объекта (новый UUID). Дедупа нет.

| Цель | Делать | Не делать |
|---|---|---|
| Убрать один файл Knowledge | Workspace → Knowledge → коллекция → удалить **этот** файл в Open WebUI | объекты в `/filer/` |
| Снести коллекцию | удалить Knowledge в Open WebUI (файлы могут остаться в чатах) | `volume rm seaweedfs_data` |
| Место на диске | `docker system df -v` / `df -h`; Filer `/filer/` — **просмотр**, nginx Basic | `down -v` |
| Вложение из чата | Files в Open WebUI, не Filer | руками ключи S3 в Filer |

Filer — смотреть. Точечное удаление — через Open WebUI, чтобы Postgres и Qdrant не разъехались.

Когда действовать: диск ВМ (часто `/var`) садится. Сначала старые Docker-**образы**, потом повторные загрузки в Knowledge.

## Тома

Никогда `docker compose down -v` и `volume rm`. Имена: `postgres_data`, `qdrant_storage`, `valkey_data`, `seaweedfs_data`, `openwebui_data`, `portainer_data`.
