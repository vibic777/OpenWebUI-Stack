# llama.cpp rerank — CPU x86, как Portainer (отдельный проект). Портов на хост нет.

Русская копия [README.md](README.md).

**Необязателен.** Основной стек работает без него. Вкл / выкл: [../RU-START.md](../RU-START.md).

Образ: `ghcr.io/ggml-org/llama.cpp:server@sha256:7fa75431b8a78f9528cab4aaf65e8ae3e13da546a3cc7221247ca81bab864d84`  
`platform: linux/amd64`. Не CUDA, не ARM.

Модель: `bge-reranker-v2-m3-Q8_0.gguf` из Hugging Face [`gpustack/bge-reranker-v2-m3-GGUF`](https://huggingface.co/gpustack/bge-reranker-v2-m3-GGUF), размер около 607 МиБ. Скачайте её отдельно: в репозитории файла нет. Перед включением сервиса сохраните настоящий файл GGUF по пути `rerank/models/model.gguf`. Подробности об артефакте: [`models/SOURCE.txt`](models/SOURCE.txt).

Запускайте команды из корня проекта (каталога с `docker-compose.yml`) после скачивания модели и запуска основного стека:

```bash
docker compose -f docker-compose.rerank.yml up -d
docker compose -f docker-compose.yml -f docker-compose.rerank-owui.yml up -d
```

Выкл (тома сохранить). Сначала вернуть Open WebUI, потом остановить llama.cpp — иначе UI стучится в мёртвый URL:

```bash
docker compose up -d
docker compose -f docker-compose.rerank.yml down
```

Никогда `down -v`. Этот id не писать в `EMBEDDING_MODEL`.

Проба (порта на хост нет):

```bash
./rerank/test-rerank.sh
# ждать: ok  и  best_index 1
```

Задайте вопрос, ответ на который содержится в Knowledge. Проверьте, обработал ли запрос reranker:

```bash
docker logs open-webui --since 5m 2>&1 | grep ExternalReranker
```

Ищите `ExternalReranker:predict:query`. Если сначала завершился ошибкой запрос embeddings (например, HTTP 400 на `/v1/embeddings`), Open WebUI мог не вызвать reranker. Порт reranker не публикуется на хост; Open WebUI обращается к нему через внутреннюю сеть Docker.
