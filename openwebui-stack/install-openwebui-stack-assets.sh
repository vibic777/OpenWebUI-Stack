#!/usr/bin/env bash
set -Eeuo pipefail

# Копирует стартовую страницу Open WebUI Stack и заменяемую картинку в системный web-root Nginx.
# Пользовательский путь относителен к ROOT, системный web-root абсолютен.
# Использование: sudo ./install-openwebui-stack-assets.sh --root /path/to --web-root /var/www/html
if [[ "${1:-}" == -h || "${1:-}" == --help ]]; then
  cat <<'HELP'
install-openwebui-stack-assets.sh — скопировать stack.html и stack-banner.svg в web-root Nginx.

Параметры:
  --root DIR          корень проекта (по умолчанию DEPLOY_ROOT или родитель openwebui-stack)
  --web-root ABS_DIR  абсолютный web-root (по умолчанию /var/www/html)
  -h, --help          показать эту справку

Требуются права root. Команда перезаписывает целевые stack.html и stack-banner.svg.

Примеры:
  sudo ./install-openwebui-stack-assets.sh
  sudo ./install-openwebui-stack-assets.sh --root /path/to --web-root /var/www/html
HELP
  exit 0
fi
die() { echo "ОШИБКА: $*" >&2; exit 1; }
root="${DEPLOY_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"; web_root="/var/www/html"
while [[ $# -gt 0 ]]; do case "$1" in --root) root="$2"; shift 2;; --web-root) web_root="$2"; shift 2;; *) die "использование: $0 [--root DIR] [--web-root ABS_DIR]";; esac; done
[[ "$EUID" -eq 0 ]] || die "запустите через sudo"
src="$root/openwebui-stack/nginx"
[[ -f "$src/stack.html" && -f "$src/stack-banner.svg" ]] || die "нет Open WebUI Stack web-артефактов в $src"
mkdir -p "$web_root"
cp -p "$src/stack.html" "$web_root/stack.html"
cp -p "$src/stack-banner.svg" "$web_root/stack-banner.svg"
echo "Установлено: $web_root/stack.html и $web_root/stack-banner.svg"
