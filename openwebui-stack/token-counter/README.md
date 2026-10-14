# Token counter

Отдельный комплект функции `token_and_time`: входные/выходные токены, суммарное использование, длительность и скорость. Работает офлайн; если провайдер не передал статистику, часть значений оценивается.

На сервере с Python 3.8+:

```bash
./install-functions.sh --email ADMIN_EMAIL
./remove-functions.sh --email ADMIN_EMAIL
```

URL по умолчанию `http://127.0.0.1:3000`; переопределить можно через `--url URL` или переменную `OWUI_URL`.

Пароль запрашивается скрыто. Можно передать API token через `OWUI_TOKEN` или пароль через `OWUI_ADMIN_PASSWORD`. Через UI используйте импорт `functions/functions.json`. Комплект меняет только `token_and_time`.
