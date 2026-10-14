# Чат: штампы, токены, выгрузки — поставить и снять

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

1. **Штампы всегда видны:** Admin → Settings → Interface → **Custom CSS** — вставить содержимое `custom-timestamps.css` → Save.  
   (Подписи меню на вашей сборке могут чуть отличаться: Interface / Интерфейс.)
2. **Токены in/out под ответом:** Admin → **Functions** → New → вставить `functions/token_and_time.py` → Save → включить **Active** и **Global**.
3. **Экспорт документов и изображений:** Function `functions/export_office.py` (Action: DOCX/XLSX/PPTX/VSDX/PDF/MD/TXT/CSV/SVG/PNG/JPG). Из корня проекта запустите `./open-webui/install-functions.sh`; вручную: Functions → New → вставить → Active + Global.

В чате Actions — кнопки у сообщения / панели чата. Filter (`token_and_time`) работает сам, если Global.

В изолированной среде не загружайте Functions из Community. Устанавливайте проверенные файлы `.py` из каталога проекта.

---

## Снять Functions

Не SQL и не `volume rm`. Только UI (нужен админ Open WebUI).

1. Войти админом → **Workspace → Functions** (или Admin → Functions).
2. Найти функцию (`token_and_time`, `export_office`).
3. Сначала можно выключить **Active** / **Global** — кнопки в чате пропадут, код ещё в базе.
4. Удалить: меню **⋯** у функции → **Delete** / Удалить → подтвердить.

После Delete записи в Postgres нет, кнопки в чате нет. Файлы в `open-webui/functions/` в копии проекта не стираются.

Снять все сразу: удалить каждую в этом списке. Другие Functions (не из этой папки) не трогать.

Если Delete нет — выключить Active+Global; это уже «не работает у людей».

---

## Снять CSS (штампы)

1. Admin → Settings → Interface → **Custom CSS**.
2. Стереть всё поле (пустое).
3. **Save**.

Штампы снова только по наведению (как из коробки). Если включали **High Contrast** ради штампов — выключить в Settings → General.

У нас `ENABLE_PERSISTENT_CONFIG=false`: после **пересоздания** контейнера `open-webui` часть настроек Админки откатывается к yaml. CSS из Админки может исчезнуть и сам. Functions в таблице Postgres **переживают** recreate (пока не `down -v`). Поэтому Functions снимать через Delete, не надеясь на рестарт.

---

## Чего не делать

- Не чистить CSS/Functions через `/filer/` и не удалять том `postgres_data`.
- Не `DELETE FROM function` в psql, пока не умеете бэкапить — UI достаточно.
- Не ставить Functions с `requirements:` / pip.
