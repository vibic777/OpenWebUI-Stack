# Message timestamps

Отдельный комплект функции `message_timestamps`, показывающей время сообщений постоянно; опционально добавляет текстовую дату в ответ. Работает офлайн.

На сервере с Python 3.8+:

```bash
./install-functions.sh --email ADMIN_EMAIL
./remove-functions.sh --email ADMIN_EMAIL
```

URL по умолчанию `http://127.0.0.1:3000`; переопределить можно через `--url URL` или переменную `OWUI_URL`.

Пароль запрашивается скрыто. Можно передать API token через `OWUI_TOKEN` или пароль через `OWUI_ADMIN_PASSWORD`. Через UI используйте импорт `functions/functions.json`. Удаление функции не снимает временные строки, уже сохранённые в старых сообщениях.
