# Экспорт кода и веб-форматов

Отдельный Action: PowerShell, Bash, Python, VBA (`.bas`), JavaScript, TypeScript, PHP, HTML, CSS, Java, C, C++, C#, Go, Rust и SQL. Скачивает один соответствующий fenced-блок как текстовый файл. Ничего не исполняет и не запускает.

Установка: `sudo ./install-functions.sh` (или `--email ADMIN_EMAIL`). Удаление только этого Action: `sudo ./remove-functions.sh`.

В ответе должен быть ровно один блок с подходящей меткой, например `powershell`, `bash`, `python`, `vba`, `typescript`, `csharp` или `sql`.
