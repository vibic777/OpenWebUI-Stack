# Open WebUI Stack

**Язык / Language:** [Русский](#русский) · [English](#english)  
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

<a id="русский"></a>
## Русский

**Open WebUI Stack** — self-hosted стек для команд, которым нужен общий веб-интерфейс к локальной языковой модели и рабочее пространство для знаний, документов и повседневных задач. Проект задуман для совместной работы **10 и более пользователей**: участники работают через Open WebUI, а приложение хранит пользователей и чаты в PostgreSQL. Фактическая одновременная нагрузка зависит от оборудования, параметров модели, контекста и настроек inference-сервера — стек не обещает фиксированную производительность без тестирования на целевой машине.

### Что можно делать

- Общаться с локальной LM-моделью через Open WebUI и отдельный OpenAI-совместимый inference-сервер, например LM Studio.
- Загружать документы в Knowledge, индексировать их и задавать вопросы по материалам через RAG.
- Использовать инструменты для извлечения текста из документов, векторного поиска и хранения файлов.
- Просить модель помогать с подготовкой скриптов, конфигов, таблиц, документов и презентаций, а затем выгружать результат в удобном формате.
- Экспортировать ответы и чаты в офисные и текстовые форматы; использовать готовые Actions для кода, изображений и структурированных данных.

### Компоненты

- **Open WebUI** — интерфейс, учётные записи, чаты, модели, Knowledge и управление RAG.
- **PostgreSQL** — постоянное хранение данных приложения и чатов.
- **Qdrant** — векторный поиск по фрагментам документов.
- **Valkey** — кэш и координация приложения.
- **SeaweedFS S3** — хранение загруженных документов и объектов.
- **Apache Tika** — извлечение текста и метаданных из поддерживаемых форматов.
- **LM Studio или другой OpenAI-совместимый сервер** — отдельный сервис для чатовой и embedding-модели; в Compose проекта не входит.
- **Nginx** — необязательный внешний reverse proxy и TLS; конфигурируется на хосте.

### Экспорт и помощь в работе с файлами

Основной мультиэкспортёр проекта — актуальный пакет [format-exporters-v2](format-exporters-v2/README.md) с четырьмя меню: **IMG, DOC, CODE и DATA**. Он выгружает изображения и схемы, документы и презентации, скрипты и исходный код, конфиги и табличные данные; поддерживает, среди прочего, DOCX, XLSX, PPTX, PDF, SVG, PNG, Mermaid, Draw.io и BPMN. Можно попросить модель подготовить содержимое, затем сохранить его в редактируемый файл. Встроенные Open WebUI Functions дополнительно экспортируют ответы в офисные и текстовые форматы и показывают счётчики токенов и временные метки. Отдельный [экспортёр чата](chat-exporter/README.md) сохраняет весь текущий диалог в DOCX, PPTX, XLSX, Markdown, TXT или JSON.

Подробнее: [актуальный мультиэкспортёр format-exporters-v2](format-exporters-v2/README.md), [встроенные Functions](open-webui/functions/README.md) и [экспорт всего чата](chat-exporter/README.md).

### Как работает RAG

Документ загружается в Open WebUI, Apache Tika извлекает текст, выбранная embedding-модель преобразует его в векторы, а Qdrant индексирует фрагменты. Файлы хранятся в SeaweedFS S3. При вопросе система находит релевантные фрагменты Knowledge и передаёт их вместе с запросом чат-модели. Опционально можно включить внешний reranker на CPU: `bge-reranker-v2-m3-Q8_0.gguf` из [Hugging Face](https://huggingface.co/gpustack/bge-reranker-v2-m3-GGUF), обслуживаемый через `llama.cpp`. Файл модели загружается отдельно и в репозиторий не включён. Стек извлекает текст через Tika; отдельного OCR-сервиса в Compose нет.

### Развёртывание и лицензия

Стек запускается через Docker Compose. Есть сценарии инициализации, обновления, проверки, резервного копирования и восстановления; образы можно подготовить для переноса на сервер без доступа к интернету. Начните с [инструкции быстрого старта](START.md). Для настройки создайте локальные конфиги через `./deploy-stack.sh --init`, укажите адреса своего хоста и inference-сервера, затем запустите стек. В репозитории хранятся только шаблоны настроек.

Авторские материалы проекта распространяются по лицензии **MIT** — см. [LICENSE](LICENSE). Сторонние компоненты, модели, названия и ресурсы сохраняют собственные лицензии и условия.

<a id="english"></a>
## English

**Open WebUI Stack** is a self-hosted environment for teams that need a shared web interface to a local language model and a practical workspace for knowledge, documents, and everyday tasks. It is designed for collaborative use by **10 or more people**: users work through Open WebUI, while PostgreSQL stores application data and chats. Actual concurrent capacity depends on hardware, the selected model, context size, and inference-server settings; the stack makes no fixed performance guarantee without testing on the target machine.

### What you can do

- Chat with a local language model through Open WebUI and a separate OpenAI-compatible inference server such as LM Studio.
- Add documents to Knowledge, index them, and ask questions grounded in those materials with retrieval-augmented generation (RAG).
- Extract text from supported documents, search indexed content, and store uploaded files.
- Use the model to help draft scripts, configuration files, spreadsheets, documents, and presentations, then export the results in practical formats.
- Export assistant responses and conversations, and use ready-made Actions for code, images, and structured data.

### Components

- **Open WebUI** — browser interface, accounts, chats, model connections, Knowledge, and RAG orchestration.
- **PostgreSQL** — persistent application data and chat storage.
- **Qdrant** — vector search over document chunks.
- **Valkey** — caching and application coordination.
- **SeaweedFS S3** — storage for uploaded documents and objects.
- **Apache Tika** — text and metadata extraction from supported formats.
- **LM Studio or another OpenAI-compatible server** — separate chat and embedding inference; it is not included in this Compose stack.
- **Nginx** — optional external reverse proxy and TLS termination, configured on the host.

### Export and file workflows

The main multi-exporter is the current [format-exporters-v2](format-exporters-v2/README.md) package, with four menus: **IMG, DOC, CODE, and DATA**. It exports images and diagrams, documents and presentations, scripts and source code, configuration files, and tabular data. Supported formats include DOCX, XLSX, PPTX, PDF, SVG, PNG, Mermaid, Draw.io, and BPMN. Ask the model to prepare the content, then save it as an editable file. Built-in Open WebUI Functions also export responses to office and text formats and display token counts and timestamps. A separate [chat exporter](chat-exporter/README.md) saves the current conversation as DOCX, PPTX, XLSX, Markdown, TXT, or JSON.

Learn more: [the current format-exporters-v2 multi-exporter](format-exporters-v2/README.md), [built-in Functions](open-webui/functions/README.md), and [full chat export](chat-exporter/README.md).

### How RAG works

A document is uploaded to Open WebUI, Apache Tika extracts its text, and the selected embedding model converts it into vectors for Qdrant to index. Files are stored in SeaweedFS S3. When a user asks a question, relevant Knowledge chunks are retrieved and sent to the chat model with the prompt. An optional CPU reranker is available: `bge-reranker-v2-m3-Q8_0.gguf` from [Hugging Face](https://huggingface.co/gpustack/bge-reranker-v2-m3-GGUF), served by `llama.cpp`. The model file must be downloaded separately and is not included in this repository. Tika extracts document text; the Compose stack does not include a separate OCR service.

### Deployment and license

The stack runs with Docker Compose. The repository includes scripts for initialization, updates, health checks, backup, and restore; container images can be prepared for transfer to an offline server. Start with the [quick-start guide](START.md). Create local configuration with `./deploy-stack.sh --init`, set your host and inference-server addresses, and then deploy. Only configuration templates are kept in the repository.

Project-authored materials are distributed under the **MIT License**; see [LICENSE](LICENSE). Third-party components, models, names, and assets remain subject to their respective licenses and terms.

---

## Быстрый старт
```bash
./images-load.sh --from <каталог с tar>      # без интернета; с интернетом это не нужно
./deploy-stack.sh --init                     # .env со случайными секретами + seaweedfs/s3.json
nano .env                                    # WEBUI_URL, LMSTUDIO_URL, LMSTUDIO_API_KEY, EMBEDDING_MODEL
./deploy-stack.sh --offline --portainer      # (с интернетом: без --offline)
./verify-stack.sh
```
Полное руководство: [этот README](README.md) и [инструкция быстрого старта](START.md).
Управление стеком в безопасном режиме и каталог команд: [ADMIN-CLI-RU.md](ADMIN-CLI-RU.md).

## Скрипты этой папки (каждый: `-h`)
| Скрипт | Назначение |
|---|---|
| `deploy-stack.sh` | развернуть с нуля (`--init`, `--offline`, `--portainer`, `--dry-run`) |
| `start-stack.sh` `stop-stack.sh` `update-stack.sh` | запуск / остановка (тома целы) / обновление (`--offline`) |
| `image-transition.sh` | переход только Open WebUI на GHCR той же OCI-версии и revision; есть rollback |
| `update-openwebui-ghcr.sh` | обновление только Open WebUI на тег GHCR (по умолчанию `main`); есть rollback |
| `update-openwebui-current.sh` | обновление только текущего `OPENWEBUI_IMAGE` без смены registry/tag; есть rollback |
| `start-portainer.sh` `stop-portainer.sh` `update-portainer.sh` | Portainer отдельным проектом |
| `backup-stack.sh` `restore-stack.sh` | бэкап/рестор PostgreSQL (пользователи, роли, чаты) и томов |
| `cleanup-chat-files.sh` | подробная справка `-h/--help`; предпросмотр и уборка только старых файлов, связанных с чатами; защищает Knowledge/каналы/заметки; требуется admin API key при удалении: [инструкция](CHAT-CLEANUP-RU.md) |
| `wipe-rag.sh` | глобальная очистка Qdrant / S3 по ключам из `.env` (`--list`, `--vectors`, `--files`, `--all`, `--volumes`); не различает чатовые файлы и Knowledge |
| `verify-stack.sh` | проверяет базовые сервисы и включённый reranker (выключенный отмечает `SKIP`); `--all` дополнительно проверяет DB/S3/Qdrant |
| `show-stack-deployment.sh` | показывает Compose-файлы и рабочий каталог из Docker labels, сервисы, image refs, локальные теги и RepoDigests |
| `full-test.sh` | агрегированные проверки стека; `--e2e-rag` гоняет DOCX upload → Tika → embeddings/Qdrant → retrieval → chat answer → cleanup |
| `nginx-upload-limit.sh` | показать/проверить лимит загрузки Nginx или безопасно изменить его; `get --probe-size 2m` только диагностирует, `set SIZE` делает резервную копию → `nginx -t` → reload |
| `brand-openwebui.sh` | временно изменить название интерфейса через `apply --name "..."`, посмотреть активное (`status`) или вернуть штатное (`restore`); после обновления контейнера применить снова |
| `check-postgres.sh` `check-valkey.sh` | отдельные read-only проверки PostgreSQL и Valkey |
| `check-embeddings.sh` `check-qdrant.sh` `check-seaweedfs.sh` | отдельные интеграционные пробы из контейнера Open WebUI; Qdrant/S3 создают и удаляют временные записи |
| `tika-check.sh` `check-rerank.sh` `check-e2e-rag.sh` | проверки Tika, reranker и полного RAG-прохода (тестовый файл удаляется) |
| `images-save.sh` `images-load.sh` | образы основного стека в tar и обратно (без интернета) |
| `enable-rerank.sh` `disable-rerank.sh` `rerank/test-rerank.sh` | опциональный reranker; модель и источник: [Hugging Face](https://huggingface.co/gpustack/bge-reranker-v2-m3-GGUF) |
| `configure-ufw.sh` `install-openwebui-stack-assets.sh` | правила UFW и копирование стартовой страницы `stack.html` с баннером `stack-banner.svg` в web-root Nginx |
| `open-webui/install-functions.sh` | установка трёх встроенных Functions Open WebUI: экспорт DOCX/XLSX/PPTX/VSDX/PDF/MD/TXT/CSV/SVG/PNG/JPG, учёт токенов и времени, временные метки сообщений |
| `chat-exporter/` | Function для экспорта всей истории текущего чата в DOCX, PPTX, XLSX, Markdown, TXT или JSON: [README](chat-exporter/README.md) |
| `message-timestamps/` `token-counter/` | отдельные комплекты установки временных меток сообщений и счётчика токенов; описание: [message timestamps](message-timestamps/README.md), [token counter](token-counter/README.md) |
| `format-exporters/{images,documents,code,data}` | четыре готовых автономных Action-меню экспорта с отдельными install/remove-скриптами: [инструкция](format-exporters/README.md) |
| `format-exporters-v2/` | актуальный пакет IMG/DOC/CODE/DATA: экспорт нескольких артефактов, Office, PDF через печать браузера, Mermaid/Draw.io/BPMN; CODE включает Power Query. [Инструкция](format-exporters-v2/README.md), [тестовые промты](format-exporters-v2/TEST-PROMPT-RU.md) |
| `format-exporters2/` | сохранённый пакет версии `2026.10.10.3` для существующих установок. Function ID совпадают с `format-exporters-v2`, поэтому устанавливайте только один пакет. Для новых установок используйте [актуальный пакет](format-exporters-v2/README.md) |

## Файлы
Compose-файлы: `docker-compose.yml` — основной стек; `docker-compose.portainer.yml` — отдельный Portainer; `docker-compose.rerank.yml` и `docker-compose.rerank-owui.yml` — reranker и его подключение; `docker-compose.no-rerank.yml` — отключение reranking-параметров Open WebUI; `docker-compose.image-transition.yml` — временный overlay для `image-transition.sh`. Также здесь `.env.example`, `policy.env` (создаётся `deploy-stack.sh`), `nginx/`, `seaweedfs/s3.json.example`, `rerank/`, `open-webui/`, `images.lock`, `FAQ.md`, `MODELS.md`.
`.env`, `seaweedfs/s3.json`, `policy.env` — секреты/локальное, в git и в релиз не входят.


