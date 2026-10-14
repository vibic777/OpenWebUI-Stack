# Модели и что где задаётся

| Что | Значение | Где |
|---|---|---|
| Модель чата | выбирается в Open WebUI (сервер инференса — LM Studio) | не в compose |
| Эмбеддинги | `text-embedding-bge-m3` (1024), OpenAI-совместимый API LM Studio | `.env` `EMBEDDING_MODEL`, `LMSTUDIO_URL` |
| Извлечение текста | Apache Tika 4; отдельного OCR-сервиса в Compose нет | `CONTENT_EXTRACTION_ENGINE=tika`, `TIKA_SERVER_URL` в `docker-compose.yml` |
| Rerank (опц.) | `bge-reranker-v2-m3-Q8_0.gguf` с Hugging Face [`gpustack/bge-reranker-v2-m3-GGUF`](https://huggingface.co/gpustack/bge-reranker-v2-m3-GGUF), CPU через llama.cpp | файл отдельно скачать в `rerank/models/model.gguf`; конфигурация: `docker-compose.rerank*.yml`, `RERANK_*` в `.env`; подробности: [`rerank/README.md`](rerank/README.md) |

Смена размерности эмбеддинга требует переиндексации (`wipe-rag.sh --vectors` + повторная загрузка), не `down -v`.
Embedding и reranker **не исправляют** плохой текст извлечения — они ищут и пересортировывают чанки.
Образы и их переменные: `images.lock`, `.env.example` и раздел об обновлении в [FAQ.md](FAQ.md).
