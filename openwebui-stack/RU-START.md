# Быстрый старт — Open WebUI Stack

1. Образы: `./images-load.sh --from <каталог>` (без интернета) — либо с интернетом ничего не нужно.
2. `./deploy-stack.sh --init` → отредактировать `.env` (`WEBUI_URL`, `LMSTUDIO_URL`, `LMSTUDIO_API_KEY`, `EMBEDDING_MODEL`). Если у LM Studio нет авторизации, укажите фиктивный ключ, который принимает ваш сервер.
3. `./deploy-stack.sh --offline --portainer` (с интернетом без `--offline`).
4. Nginx + TLS: следуйте [nginx/RU-README.md](nginx/RU-README.md); при необходимости установите стартовую страницу и баннер командой `./install-openwebui-stack-assets.sh`.
5. `./verify-stack.sh` → «ALL PASS».
6. Быстрый набор: `./full-test.sh`. Получить список моделей через API: `./list-models.sh` (нужен admin API-ключ Open WebUI). После выбора чат-модели: `export OPENWEBUI_E2E_MODEL='<ID модели>'` и `./full-test.sh --e2e-rag`. Ключ передаётся через `OPENWEBUI_API_KEY` или путь `OPENWEBUI_API_KEY_FILE`; ключ модели не нужен. Подробно: `RAG-E2E-HELP.md`. Образы и Compose: `./show-stack-deployment.sh`.
7. Плагины: `cd open-webui && ./install-functions.sh --email <админ> --ask-password` (пароль запрашивается скрыто; не передавайте его аргументом команды).
8. Rerank (по желанию): скачайте `bge-reranker-v2-m3-Q8_0.gguf` из [Hugging Face](https://huggingface.co/gpustack/bge-reranker-v2-m3-GGUF), сохраните как `rerank/models/model.gguf` и запустите `./enable-rerank.sh`.

Готово, когда `open-webui`, `openwebui-postgres`, `openwebui-qdrant`, `openwebui-valkey`, `openwebui-seaweedfs` и `openwebui-tika` работают (healthcheck — где он задан). Portainer и reranker — дополнительные слои.

Перед изменением данных создайте резервную копию: `./backup-stack.sh`. Для обычной уборки чатовых файлов используйте `./cleanup-chat-files.sh` сначала без флагов (предпросмотр); `wipe-rag.sh` глобально очищает Qdrant/S3 и может удалить Knowledge.

Не запускайте `docker compose down -v` на стеке с нужными данными.
