#!/usr/bin/env bash
# Convenience launcher for the Open WebUI stack.
set -euo pipefail
root="${DEPLOY_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
args=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --root)
      [[ $# -ge 2 && -n "$2" ]] || { echo "ERROR: --root requires a directory" >&2; exit 2; }
      root="$2"; shift 2;;
    *) args+=("$1"); shift;;
  esac
done
root="$(cd "$root" && pwd)"
stack="$root/openwebui-stack/deploy-stack.sh"
[[ -f "$stack" ]] || { echo "ERROR: stack deploy script not found: $stack" >&2; exit 1; }
exec "$stack" "${args[@]}"
