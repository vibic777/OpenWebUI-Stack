#!/usr/bin/env bash
set -Eeuo pipefail

# Настройка UFW для Open WebUI Stack.
# По умолчанию только план; применение требует --apply.
# Использование:
#   sudo ./configure-ufw.sh            # plan for this project directory
#   sudo ./configure-ufw.sh --apply
if [[ "${1:-}" == -h || "${1:-}" == --help ]]; then
  cat <<'HELP'
Использование: sudo ./configure-ufw.sh [--ssh-port PORT] [--apply]
Показывается имя каталога проекта.
По умолчанию только показывает план правил. --apply применяет правила UFW:
разрешает SSH/HTTP/HTTPS и запрещает остальные входящие подключения.
HELP
  exit 0
fi

die() { echo "ОШИБКА: $*" >&2; exit 1; }
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; mode="$(basename "$HERE")"; apply=0; ssh_port="${SSH_PORT:-22}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply) apply=1; shift;;
    --ssh-port) ssh_port="$2"; shift 2;;
    *) die "использование: $0 [--ssh-port PORT] [--apply]";;
  esac
done
[[ "$EUID" -eq 0 ]] || die "запустите через sudo"
command -v ufw >/dev/null 2>&1 || die "ufw не установлен"

echo "Профиль UFW: $mode"
echo "Разрешается: SSH $ssh_port/tcp, HTTP 80/tcp, HTTPS 443/tcp"
echo "Остальные входящие подключения запрещаются; исходящие остаются разрешены."
(( apply )) || { echo "План. Для применения добавьте --apply."; exit 0; }

# Сначала разрешаем SSH, затем меняем default policy, чтобы не потерять доступ.
ufw allow "$ssh_port/tcp" comment "SSH administration"
ufw allow 80/tcp comment "HTTP redirect"
ufw allow 443/tcp comment "HTTPS Nginx"
ufw default deny incoming
ufw default allow outgoing
ufw --force enable
ufw status verbose
