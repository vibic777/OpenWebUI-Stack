# Чат: штампы, токены, выгрузки — поставить и снять

Альтернативное имя этого руководства; основной файл — [chat-ui.md](chat-ui.md).

Это **не compose**. Живёт в **Postgres** (Functions) и в настройках UI (CSS), не в образе.  
`docker compose up` их сам не ставит и **не удаляет**. Тома не трогать (`down -v` нельзя).

Для автономной установки используйте файлы проекта и зависимости, уже включённые в образ. Не устанавливайте функции из Community, если среда не должна обращаться к внешним ресурсам.

Файлы проекта (`functions/*.py`, `custom-timestamps.css`) после удаления функции в UI остаются на диске: это исходные копии для повторной установки.

---

## Что уже в продукте (ставить не надо, удалять нечего)

| Нужно | Где |
|---|---|
| Весь чат → **PDF / Markdown / JSON** | меню чата **⋯** → Download / Export |
| Одна markdown-таблица → **CSV** | иконки на таблице в ответе |
| Токены одного ответа | иконка **i** у сообщения модели (если LM Studio отдал `usage`) |
| Штамп по наведению | навести на имя («Вы» / модель). Либо Settings → General → **High Contrast** |

---

## Поставить (Admin)

1. **Штампы всегда видны:** Admin → Settings → Interface → **Custom CSS** — вставить `custom-timestamps.css` → Save.
2. **Токены in/out под ответом:** Admin → **Functions** → New → вставить `functions/token_and_time.py` → Save → **Active** и **Global**.
3. **Экспорт документов и изображений:** Function `functions/export_office.py` (Action: DOCX/XLSX/PPTX/VSDX/PDF/MD/TXT/CSV/SVG/PNG/JPG). Из корня проекта запустите `./open-webui/install-functions.sh`; вручную: Functions → New → вставить → Active + Global.

В изолированной среде не загружайте Functions из Community. Устанавливайте проверенные файлы `.py` из каталога проекта.

---

## Снять Functions

Не SQL и не `volume rm`. Только UI (админ Open WebUI).

1. **Workspace → Functions** (или Admin → Functions).
2. Найти `token_and_time`, `export_office`
3. Можно выключить **Active** / **Global**.
4. **⋯** → **Delete** / Удалить.

Файлы в `open-webui/functions/` в копии проекта не стираются.

---

## Снять CSS (штампы)

1. Admin → Settings → Interface → **Custom CSS**.
2. Очистить поле.
3. **Save**.

Если включали **High Contrast** ради штампов — выключить в Settings → General.

`ENABLE_PERSISTENT_CONFIG=false`: после пересоздания `open-webui` CSS из Админки может пропасть сам. Functions в Postgres **переживают** recreate (пока не `down -v`). Снимать Functions через Delete.

## Чего не делать

- Не чистить CSS/Functions через `/filer/` и не удалять том `postgres_data`.
- Не `DELETE FROM function` в psql без бэкапа.
- Не ставить Functions с `requirements:` / pip.
