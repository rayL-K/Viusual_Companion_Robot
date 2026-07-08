#!/usr/bin/env bash
set -Eeuo pipefail

readonly SERVICES=(
  visual-companion-emotion.service
  visual-companion-vlm.service
  visual-companion-control.service
  visual-companion-cloudflared.service
)
readonly SCRIPT_PATH="$(readlink -f -- "${BASH_SOURCE[0]}")"
readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${SCRIPT_PATH}")" && pwd)"
readonly PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"
readonly ACTION="${1:-start}"

if [[ ${EUID} -ne 0 && ${ACTION} != status ]]; then
  exec sudo -- "$0" "$@"
fi

log() {
  printf '[Visual Companion] %s\n' "$*"
}

fail() {
  log "失败：$*"
  log "最近服务日志："
  journalctl -u visual-companion-emotion.service \
    -u visual-companion-vlm.service \
    -u visual-companion-control.service \
    -u visual-companion-cloudflared.service \
    -n 60 --no-pager || true
  exit 1
}

remove_obsolete_voxcpm_service() {
  if systemctl cat visual-companion-voxcpm.service >/dev/null 2>&1; then
    log "移除旧的常驻 VoxCPM 服务，改由控制网关按请求运行"
    systemctl disable --now visual-companion-voxcpm.service || true
    rm -f /etc/systemd/system/visual-companion-voxcpm.service
    systemctl daemon-reload
  fi
  # 仅在一键启动/重启入口清理上次异常退出留下的服务进程。
  pkill -x voxcpm-server 2>/dev/null || true
}

require_deployment() {
  [[ -x "${PROJECT_ROOT}/.venv/bin/python" ]] \
    || fail "缺少 ${PROJECT_ROOT}/.venv/bin/python，请先完成板端部署"
  [[ -f "${PROJECT_ROOT}/main/config/board.env" ]] \
    || fail "缺少 main/config/board.env"
  [[ -x /opt/visual-companion-voxcpm/bin/voxcpm-server ]] \
    || fail "缺少 VoxCPM.cpp；请先运行 tools/board/install_voxcpm_cpp.sh"
  local service
  for service in "${SERVICES[@]}"; do
    [[ -f "${PROJECT_ROOT}/tools/systemd/${service}" ]] \
      || fail "仓库缺少 systemd 单元：${service}"
  done
}

install_service_units() {
  local service
  for service in "${SERVICES[@]}"; do
    install -m 644 "${PROJECT_ROOT}/tools/systemd/${service}" "/etc/systemd/system/${service}"
  done
}

wait_for_url() {
  local name="$1"
  local url="$2"
  local attempts="${3:-90}"
  local attempt
  for ((attempt = 1; attempt <= attempts; attempt += 1)); do
    if curl --fail --silent --show-error --max-time 3 "${url}" >/dev/null 2>&1; then
      log "${name} 已就绪：${url}"
      return 0
    fi
    sleep 1
  done
  fail "${name} 在 ${attempts} 秒内没有通过健康检查"
}

show_status() {
  systemctl --no-pager --full status "${SERVICES[@]}" \
    | sed -n -E '/^●|Active:|Main PID:/p' || true
  log "板端地址：$(hostname -I 2>/dev/null | xargs || true)"
}

start_services() {
  local mode="${1:-start}"
  require_deployment
  remove_obsolete_voxcpm_service
  install_service_units
  systemctl daemon-reload
  systemctl reset-failed "${SERVICES[@]}" || true
  systemctl enable "${SERVICES[@]}"
  if [[ ${mode} == restart ]]; then
    systemctl restart "${SERVICES[@]}"
  else
    systemctl start "${SERVICES[@]}"
  fi
  wait_for_url "人脸/情绪/主动说话人服务" "http://127.0.0.1:8766/health"
  wait_for_url "Qwen3-VL 语义视觉服务" "http://127.0.0.1:8767/health"
  wait_for_url "统一控制服务" "http://127.0.0.1:8765/health"
  wait_for_url "统一视觉模型" "http://127.0.0.1:8765/vision-health"
  systemctl is-active --quiet visual-companion-cloudflared.service \
    || fail "Cloudflare Tunnel 未运行"
  log "全部服务已启动；公网入口：https://robot.veyralux.org"
  show_status
}

case "${ACTION}" in
  start)
    start_services start
    ;;
  restart)
    start_services restart
    ;;
  status)
    show_status
    ;;
  stop)
    systemctl stop \
      visual-companion-cloudflared.service \
      visual-companion-control.service \
      visual-companion-vlm.service \
      visual-companion-emotion.service
    log "全部服务已停止"
    ;;
  *)
    printf '用法：%s [start|restart|status|stop]\n' "$0" >&2
    exit 2
    ;;
esac
