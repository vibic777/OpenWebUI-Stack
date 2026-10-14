# Open WebUI Stack

Основной проект стека находится в [`openwebui-stack`](openwebui-stack/README.md). Каталог содержит Docker Compose конфигурацию, эксплуатационные скрипты и документацию Open WebUI.

- Развёртывание из корня: `./deploy-stack.sh --help` (перенаправляет запуск в `openwebui-stack/deploy-stack.sh`).
- Конфиги Nginx: [`openwebui-stack/nginx/`](openwebui-stack/nginx/).
- Аудит безопасности: [`openwebui-stack/security/README-RU.md`](openwebui-stack/security/README-RU.md).
- `archive/` содержит прежние копии и временные артефакты. Каталог исключён из Git и остаётся только локально.

Локальные `openwebui-stack/.env`, `openwebui-stack/seaweedfs/s3.json` и файлы доступа Nginx содержат секреты; они исключены из Git.
