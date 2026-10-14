# Автономные экспортёры Open WebUI

Пакет содержит четыре самостоятельных Action-кнопки: изображения (IMG), документы (DOC), код (CODE) и данные (DATA). Каждую можно устанавливать и удалять отдельно. Экспортируется ответ ассистента, под которым нажата кнопка; выбранный формат сохраняется в отдельный файл. Actions работают локально в браузере и не требуют отдельного сервиса или скачивания библиотек.

| Кнопка | Форматы |
|---|---|
| IMG | SVG, PNG, JPG, WebP |
| DOC | DOCX, XLSX, PPTX, VSDX, PDF, Markdown, TXT |
| CODE | блоки исходного кода и скриптов, включая PS1, SH, Python, JavaScript, SQL и Power Query |
| DATA | JSON, JSONL, XML, YAML, TOML, INI, CONF, ENV, Properties, CSV, TSV |

В форматах DOCX/XLSX/PPTX используются библиотеки, уже входящие в образ Open WebUI. VSDX строится встроенным генератором; сложные схемы могут потребовать ручной доводки в Visio. Полные сценарии проверки и пользовательские промты: [TEST-PROMPT-ALL-FORMATS-RU.md](TEST-PROMPT-ALL-FORMATS-RU.md), [USER-GUIDE-RU.md](USER-GUIDE-RU.md) и [USER-GUIDE-BEGINNER-RU.md](USER-GUIDE-BEGINNER-RU.md).

## Установка и удаление

Из этого каталога установите все четыре Actions через API Open WebUI:

```bash
./install-functions.sh --email ADMIN_EMAIL
```

Скрипт запросит пароль администратора скрытым вводом. Для установки/удаления одного Action используйте одноимённые скрипты в `images/`, `documents/`, `code/` или `data/`. Удаление пакета не затрагивает другие Open WebUI Functions.

Минимальная версия Open WebUI указана в манифестах Actions. После установки включите каждую функцию как Active и Global, если установщик этого не сделал.

## Сборка и проверки

Из корня проекта выполните `python3 format-exporters/build_all.py`. Готовые Actions включают нужные helper-коды; сборщик может использовать их для восстановления пакета, если исходные каталоги helper-проектов не поставляются. Unit-тесты запускаются из корня: `python -m unittest discover -s tests -p test_format_exporters.py -v`.

После пересборки запустите соответствующий установщик, чтобы обновить Functions, сохранённые в Open WebUI. Изменение файлов на диске само по себе не обновляет установленную функцию.