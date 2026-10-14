# Стек Open WebUI

Полное описание компонентов, схемы RAG, вариантов развёртывания и обслуживания приведено в [основном README](README.md) в разделе «Русский».

## Быстрый запуск

1. Подготовьте `.env` и runtime-конфигурацию SeaweedFS: `./deploy-stack.sh --init`.
2. Заполните адрес интерфейса, адрес совместимого с OpenAI API сервера моделей и embedding-модель. Проверьте локальные секреты и не публикуйте runtime-файлы.
3. При offline-развёртывании загрузите образы через `./images-load.sh --from <каталог>`; затем запустите `./deploy-stack.sh --offline`. Для обычного запуска используйте `./deploy-stack.sh`.
4. Проверьте конфигурацию и состояние контейнеров командой `./verify-stack.sh`.

Подробный порядок действий: [START.md](START.md). Команды и их влияние на данные: [ADMIN-CLI-RU.md](ADMIN-CLI-RU.md).

## Состав

Основной стек: Open WebUI, PostgreSQL, Qdrant, Valkey, SeaweedFS S3 и Apache Tika. Nginx и сервер инференса настраиваются отдельно. Portainer и reranker подключаются как дополнительные компоненты.

Модель reranker, источник и способ подключения описаны в [RU-MODELS.md](RU-MODELS.md) и [руководстве reranker](rerank/RU-README.md). Сам GGUF-файл в публикацию не входит.
