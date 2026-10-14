#!/usr/bin/env bash
# Inspect or change the host Nginx request-body limit for the Open WebUI vhost.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
  cat <<'HELP'
Использование:
  sudo ./nginx-upload-limit.sh get [--server-name HOST] [--probe-size 2m]
  sudo ./nginx-upload-limit.sh set SIZE [--server-name HOST] [--dry-run] [--yes]

get    Показывает текущий лимит Nginx для vhost Open WebUI. --probe-size
       отправляет синтетический запрос без авторизации через HTTPS, чтобы
       проверить, пропускает ли прокси тело такого размера. Файл не создаётся.
set    Меняет client_max_body_size только в найденном server-блоке,
       предварительно находит его через nginx -T, сохраняет резервную копию,
       выполняет nginx -t и только при успехе перезагружает Nginx. При ошибке
       проверки или reload исходный конфиг восстанавливается автоматически.

nginx -T — чтение/разбор активной конфигурации, nginx -t — проверка
синтаксиса изменённой конфигурации. HTTP-проба выполняется отдельно:
  sudo ./nginx-upload-limit.sh get --probe-size 2m
Полная проверка запускает эту read-only пробу, но не меняет конфиг и не делает reload.

SIZE — положительный размер, например 100m (рекомендуется для файлов около
50 МБ). По умолчанию vhost определяется по WEBUI_URL из .env. Если есть
несколько подходящих vhost, укажите --server-name.
set без --yes запрашивает подтверждение: введите y/да; Enter отменяет изменение.
--yes подтверждает заранее, --dry-run только показывает план и ничего не меняет.

Для проверки загрузки и этого лимита из полного набора: sudo ./full-test.sh
Изменение Nginx на хосте выполняйте только после проверки команды set.
HELP
}

if [[ "${1:-}" == -h || "${1:-}" == --help ]]; then usage; exit 0; fi
if [[ $EUID -ne 0 ]]; then exec sudo -- "$0" "$@"; fi
exec python3 - "$HERE" "$@" <<'PY'
import datetime
import os
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(sys.argv[1])
args = sys.argv[2:]

def die(message):
    print("ОШИБКА: " + message, file=sys.stderr)
    raise SystemExit(1)

def parse_size(value):
    match = re.fullmatch(r"([1-9][0-9]*)([kKmMgG]?)", value)
    if not match:
        die(f"неверный размер {value!r}; используйте положительное число с суффиксом k/m/g, например 100m")
    amount = int(match.group(1))
    unit = match.group(2).lower()
    multiplier = {"": 1, "k": 1024, "m": 1024**2, "g": 1024**3}[unit]
    return amount * multiplier

def parse_cli(argv):
    if not argv or argv[0] not in ("get", "set"):
        die("укажите действие get или set; справка: ./nginx-upload-limit.sh --help")
    action = argv[0]
    pos = 1
    size = None
    if action == "set":
        if pos >= len(argv) or argv[pos].startswith("--"):
            die("для set укажите SIZE, например set 100m")
        size = argv[pos]
        parse_size(size)
        pos += 1
    server_name = None
    probe_size = None
    dry_run = False
    yes = False
    while pos < len(argv):
        item = argv[pos]
        if item == "--server-name" and pos + 1 < len(argv):
            server_name = argv[pos + 1]
            pos += 2
        elif item == "--probe-size" and pos + 1 < len(argv):
            probe_size = argv[pos + 1]
            parse_size(probe_size)
            pos += 2
        elif item == "--dry-run":
            dry_run = True
            pos += 1
        elif item == "--yes":
            yes = True
            pos += 1
        else:
            die(f"неизвестная опция {item!r}; справка: ./nginx-upload-limit.sh --help")
    if action == "set" and probe_size:
        die("--probe-size применяется только с get")
    return action, size, server_name, probe_size, dry_run, yes

def code_only(line):
    quote = None
    escaped = False
    out = []
    for char in line:
        if escaped:
            out.append(char)
            escaped = False
        elif char == "\\":
            out.append(char)
            escaped = True
        elif quote:
            out.append(char)
            if char == quote:
                quote = None
        elif char in ("'", '"'):
            quote = char
            out.append(char)
        elif char == "#":
            break
        else:
            out.append(char)
    return "".join(out)

def brace_delta(line):
    code = code_only(line)
    return code.count("{") - code.count("}")

def iter_blocks(lines, keyword):
    blocks = []
    start = None
    depth = 0
    for index, line in enumerate(lines):
        code = code_only(line)
        if start is None and re.search(r"^\s*" + re.escape(keyword) + r"\s*\{", code):
            start = index
            depth = 0
        if start is not None:
            depth += brace_delta(line)
            if depth == 0:
                blocks.append((start, index + 1, lines[start:index + 1]))
                start = None
    return blocks

def directives(block_lines, depth_wanted):
    result = []
    depth = 0
    for index, line in enumerate(block_lines):
        code = code_only(line)
        if depth == depth_wanted:
            match = re.match(r"^\s*client_max_body_size\s+([^;\s]+)\s*;", code)
            if match:
                result.append((index, match.group(1)))
        depth += brace_delta(line)
    return result

def server_meta(lines):
    code = "\n".join(code_only(line) for line in lines)
    names = []
    for value in re.findall(r"(?m)^\s*server_name\s+([^;]+);", code):
        names.extend(value.split())
    proxies = re.findall(r"(?m)^\s*proxy_pass\s+([^;]+);", code)
    listens = re.findall(r"(?m)^\s*listen\s+([^;]+);", code)
    return names, proxies, listens

def read_webui_url():
    path = ROOT / ".env"
    if not path.exists():
        die(f"не найден {path}; укажите --server-name HOST")
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = re.match(r"^\s*WEBUI_URL\s*=\s*(.*?)\s*$", line)
        if match:
            value = match.group(1).strip("\"'")
            parsed = urllib.parse.urlparse(value)
            if parsed.hostname:
                return value, parsed
    die(f"не удалось определить хост из WEBUI_URL в {path}; укажите --server-name HOST")

def load_active_server(requested_host):
    nginx = shutil.which("nginx")
    if not nginx:
        die("nginx не найден на этом хосте")
    proc = subprocess.run([nginx, "-T"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if proc.returncode:
        die("nginx -T завершился с ошибкой:\n" + proc.stdout[-2000:])
    source = None
    candidates = []
    lines = proc.stdout.splitlines(keepends=True)
    for start, end, block in iter_blocks(lines, "server"):
        for before in reversed(lines[:start]):
            config = re.match(r"^# configuration file (.+):\s*$", before.rstrip("\r\n"))
            if config:
                source = config.group(1)
                break
        names, proxies, listens = server_meta(block)
        if requested_host.lower() not in [name.lower() for name in names] or not proxies:
            continue
        candidates.append({"source": source, "lines": block, "start": start, "end": end,
                           "names": names, "proxies": proxies, "listens": listens})
    if not candidates:
        die(f"в nginx -T не найден proxy server-блок для server_name {requested_host!r}")
    if len(candidates) > 1:
        print("Подходящие proxy server-блоки:", file=sys.stderr)
        for item in candidates:
            print(f"  source={item['source']} listen={item['listens']} proxy_pass={item['proxies']}", file=sys.stderr)
        die("найдено несколько proxy vhost; задайте --server-name или устраните неоднозначность")
    selected = candidates[0]
    if not selected["source"] or not Path(selected["source"]).exists():
        die("не удалось определить исходный файл активного Nginx server-блока")
    selected["path"] = Path(selected["source"]).resolve()
    selected["dump"] = proc.stdout
    return selected

def current_limit(server):
    server_values = directives(server["lines"], 1)
    nested_values = directives(server["lines"], 2)
    http_values = []
    for _, _, block in iter_blocks(server["dump"].splitlines(keepends=True), "http"):
        http_values.extend(value for _, value in directives(block, 1))
    inherited = http_values[-1] if http_values else "1m (Nginx default)"
    effective = server_values[-1][1] if server_values else inherited
    return effective, server_values, nested_values, inherited

def probe_upload(url, byte_count):
    parsed = urllib.parse.urlparse(url)
    scheme = parsed.scheme or "https"
    host = parsed.hostname
    port = parsed.port or (443 if scheme == "https" else 80)
    prefix = parsed.path.rstrip("/")
    target = prefix + "/api/v1/files/?"
    body = b"openwebui-nginx-body-size-probe\n" + b"x" * max(0, byte_count - 32)
    request = urllib.request.Request(
        urllib.parse.urlunparse((scheme, parsed.netloc, target, "", "", "")),
        data=body,
        method="POST",
        headers={"Content-Type": "application/octet-stream", "Content-Length": str(len(body))},
    )
    context = ssl._create_unverified_context() if scheme == "https" else None
    if context:
        print("INFO: TLS-проверка отключена только для локального синтетического запроса без ключа и файла.")
    status = None
    ctype = ""
    detail = ""
    try:
        with urllib.request.urlopen(request, timeout=20, context=context) as response:
            status = response.status
            ctype = response.headers.get("Content-Type", "")
            detail = response.read(300).decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        status = error.code
        ctype = error.headers.get("Content-Type", "")
        detail = error.read(300).decode("utf-8", "replace")
    except Exception as error:
        print(f"FAIL: HTTPS-проба не прошла: {type(error).__name__}: {error}")
        return False
    if status == 413:
        print(f"FAIL: Nginx отклонил синтетическое тело {len(body)} байт (HTTP 413, Content-Type={ctype}).")
        print("Ответ содержит HTML вместо API JSON; поднимите client_max_body_size и повторите проверку.")
        return False
    if status == 401 and "json" in ctype.lower():
        print(f"PASS: Nginx пропустил тело {len(body)} байт до Open WebUI; API ожидаемо вернул HTTP 401 без ключа.")
        return True
    print(f"FAIL: неожиданный ответ от upload API: HTTP {status}, Content-Type={ctype}; {detail[:180]!r}")
    return False

action, new_size, explicit_host, probe_size, dry_run, yes = parse_cli(args)
webui_url, parsed_url = read_webui_url()
host = explicit_host or parsed_url.hostname
server = load_active_server(host)
effective, server_values, nested_values, inherited = current_limit(server)

if action == "get":
    print(f"Nginx source: {server['source']}")
    print(f"Open WebUI vhost: {host}; proxy_pass={', '.join(server['proxies'])}")
    print(f"client_max_body_size (server effective): {effective}")
    print(f"HTTP inherited value: {inherited}")
    if nested_values:
        print("Переопределения в location (проверьте применимость к /api/v1/files/): " +
              ", ".join(value for _, value in nested_values))
    if probe_size:
        ok = probe_upload(webui_url, parse_size(probe_size))
        raise SystemExit(0 if ok else 1)
    raise SystemExit(0)

if nested_values:
    die("внутри vhost есть location-level client_max_body_size; автоматическая правка server-level может не примениться к upload. Значения: " +
        ", ".join(value for _, value in nested_values))
if len(server_values) > 1:
    print("INFO: несколько server-level директив будут приведены к одному значению.")

path = server["path"]
with path.open("r", encoding="utf-8", newline="") as stream:
    original = stream.read()
file_lines = original.splitlines(keepends=True)
blocks = [b for b in iter_blocks(file_lines, "server") if host.lower() in [n.lower() for n in server_meta(b[2])[0]] and server_meta(b[2])[1]]
if len(blocks) != 1:
    die(f"в исходном файле {path} найдено {len(blocks)} подходящих proxy server-блоков")
start, end, block_lines = blocks[0]
old_lines = list(file_lines)
depth = 0
changed = 0
for index in range(start, end):
    line = file_lines[index]
    code = code_only(line)
    if depth == 1 and re.match(r"^\s*client_max_body_size\s+[^;]+;", code):
        file_lines[index] = re.sub(r"(\bclient_max_body_size\s+)[^;]+(;)", rf"\g<1>{new_size}\g<2>", line, count=1)
        changed += 1
    depth += brace_delta(line)
if changed == 0:
    opening = re.match(r"^(\s*server\s*\{)(.*)$", file_lines[start])
    if not opening:
        die("не удалось найти строку открытия server-блока для безопасной вставки")
    newline = "\r\n" if file_lines[start].endswith("\r\n") else "\n"
    indent = "    "
    for line in file_lines[start + 1:end]:
        match = re.match(r"^(\s+)\S", line)
        if match:
            indent = match.group(1)
            break
    file_lines.insert(start + 1, f"{indent}client_max_body_size {new_size};{newline}")

if dry_run:
    print(f"DRY-RUN: изменился бы {path}: client_max_body_size {effective} -> {new_size}")
    raise SystemExit(0)
if not yes:
    try:
        answer = input(f"Изменить лимит Nginx для {host}: {effective} -> {new_size} в {path}? [y/N] ")
    except EOFError:
        answer = ""
    if answer.strip().lower() not in ("y", "yes", "д", "да"):
        print("Отменено; конфиг не менялся.")
        raise SystemExit(0)

stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
backup = path.with_name(path.name + ".bak-" + stamp)
if backup.exists():
    backup = path.with_name(path.name + ".bak-" + stamp + f"-{os.getpid()}")
shutil.copy2(path, backup)
metadata = path.stat()
fd, temp_name = tempfile.mkstemp(prefix="." + path.name + ".limit-", dir=str(path.parent))
try:
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
        stream.write("".join(file_lines))
    os.chmod(temp_name, metadata.st_mode & 0o7777)
    os.chown(temp_name, metadata.st_uid, metadata.st_gid)
    os.replace(temp_name, path)
except BaseException:
    try: os.unlink(temp_name)
    except FileNotFoundError: pass
    raise

nginx = shutil.which("nginx")
test = subprocess.run([nginx, "-t"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
if test.returncode:
    shutil.copy2(backup, path)
    print("nginx -t не прошёл; восстановлен исходный конфиг из " + str(backup), file=sys.stderr)
    print(test.stdout, file=sys.stderr)
    raise SystemExit(1)
reload_cmd = ["systemctl", "reload", "nginx"] if shutil.which("systemctl") else [nginx, "-s", "reload"]
reload = subprocess.run(reload_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
if reload.returncode:
    shutil.copy2(backup, path)
    subprocess.run([nginx, "-t"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(reload_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print("перезагрузка Nginx не прошла; исходный конфиг восстановлен из " + str(backup), file=sys.stderr)
    print(reload.stdout, file=sys.stderr)
    raise SystemExit(1)
print(f"PASS: установлен client_max_body_size {new_size} для {host}; Nginx проверен и перезагружен.")
print(f"Резервная копия: {backup}")
PY
