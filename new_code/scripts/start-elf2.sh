#!/usr/bin/env bash
set -Eeuo pipefail

readonly ACTION="${1:-start}"
readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly V2_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
readonly PROJECT_ROOT="$(cd -- "${V2_ROOT}/.." && pwd)"
readonly SERVICES=(veyrasoul-v2.service veyrasoul-v2-cloudflared.service)

log() { printf '[VeyraSoul V2] %s\n' "$*"; }
fail() { log "失败：$*" >&2; exit 1; }

if [[ ${EUID} -ne 0 && ${ACTION} != status ]]; then
  exec sudo -- "$0" "$@"
fi

install_units() {
  install -m 644 "${V2_ROOT}/deploy/systemd/veyrasoul-v2.service" /etc/systemd/system/
  install -m 644 "${V2_ROOT}/deploy/systemd/veyrasoul-v2-cloudflared.service" /etc/systemd/system/
  systemctl daemon-reload
}

require_runtime() {
  [[ -x "${V2_ROOT}/backend/.venv/bin/python" ]] || fail "缺少 backend/.venv，请先安装板端 Python 依赖"
  [[ -f "${V2_ROOT}/web/dist/index.html" ]] || fail "缺少 web/dist，请先执行 npm ci && npm run build"
  [[ -r /etc/veyrasoul/veyrasoul.env ]] || fail "缺少 /etc/veyrasoul/veyrasoul.env"
  [[ -r /etc/cloudflared/token ]] || fail "缺少 /etc/cloudflared/token"
}

wait_for_health() {
  for _ in {1..90}; do
    curl -fsS --max-time 2 http://127.0.0.1:8875/v2/health >/dev/null && return 0
    sleep 1
  done
  journalctl -u veyrasoul-v2.service -n 80 --no-pager || true
  fail "Gateway 在 90 秒内未就绪"
}

case "${ACTION}" in
  start|restart)
    require_runtime
    install_units
    systemctl enable "${SERVICES[@]}"
    # 同一个 Tunnel token 不能被 V1/V2 同时占用；切换时保留 V1 单元但停止它，便于回滚。
    systemctl stop visual-companion-cloudflared.service 2>/dev/null || true
    systemctl "${ACTION}" veyrasoul-v2.service
    wait_for_health
    systemctl "${ACTION}" veyrasoul-v2-cloudflared.service
    systemctl is-active --quiet "${SERVICES[@]}" || fail "至少一个 V2 服务未运行"
    log "服务已启动：https://robot.veyralux.org"
    ;;
  stop)
    systemctl stop "${SERVICES[@]}"
    log "V2 服务已停止"
    ;;
  status)
    systemctl --no-pager --full status "${SERVICES[@]}" | sed -n -E '/^●|Active:|Main PID:/p' || true
    ;;
  rollback)
    systemctl disable --now "${SERVICES[@]}" 2>/dev/null || true
    systemctl enable --now visual-companion-cloudflared.service
    log "公网 Tunnel 已回滚到 V1"
    ;;
  *)
    printf '用法：%s [start|restart|status|stop|rollback]\n' "$0" >&2
    exit 2
    ;;
esac
