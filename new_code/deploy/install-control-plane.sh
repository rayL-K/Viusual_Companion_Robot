#!/usr/bin/env bash
# 一次性受信安装器：仅由主机管理员从已审阅的仓库工作树执行。
set -Eeuo pipefail
umask 077

readonly INSTALL_ROOT="/home/wenkang/anima"
readonly SOURCE_ROOT="${INSTALL_ROOT}/source"
readonly RELEASES_ROOT="${INSTALL_ROOT}/releases"
readonly MODELS_ROOT="${INSTALL_ROOT}/models"
readonly RUNTIME_ROOT="${INSTALL_ROOT}/.venv"
readonly CONTROL_ROOT="/opt/anima-control"
readonly LAUNCHER_PATH="/usr/local/sbin/anima-deploy"
readonly CONFIG_ROOT="/etc/anima"
readonly DEPLOY_STATE="/var/lib/anima-deploy"
readonly PACKAGE_ROOT="$(cd -- "$(dirname -- "$(readlink -f -- "$0")")/.." && pwd -P)"
readonly DEPLOY_OWNER="wenkang"

log() { printf '[Anima control install] %s\n' "$*"; }
fail() { log "失败：$*" >&2; exit 1; }

require_root() {
  [[ ${EUID} -eq 0 ]] || fail "必须由 root 执行：sudo bash deploy/install-control-plane.sh"
}

require_commands() {
  local name
  for name in chown chmod cp find getent groupadd id install python3 readlink rm systemctl useradd; do
    command -v "${name}" >/dev/null 2>&1 || fail "缺少命令：${name}"
  done
}

require_regular_file() {
  local path="$1"
  [[ -f "${path}" && ! -L "${path}" ]] || fail "受信安装输入缺失或为符号链接：${path}"
}

require_regular_tree() {
  local path="$1"
  local violation
  [[ -d "${path}" && ! -L "${path}" ]] || fail "受信安装目录缺失或为符号链接：${path}"
  violation="$(find "${path}" -xdev \( -type l -o \( ! -type f -a ! -type d \) \) -print -quit)"
  [[ -z "${violation}" ]] || fail "受信安装目录含不允许的条目：${violation}"
}

ensure_service_account() {
  local name="$1"
  getent group "${name}" >/dev/null 2>&1 || groupadd --system "${name}"
  id -u "${name}" >/dev/null 2>&1 || \
    useradd --system --gid "${name}" --home-dir /nonexistent --shell /usr/sbin/nologin "${name}"
}

verify_root_owned_tree() {
  local path="$1"
  local violation
  [[ -d "${path}" && ! -L "${path}" ]] || fail "目录异常：${path}"
  # Python venvs normally contain compatibility symlinks (for example
  # lib64 -> lib). A symlink's displayed 0777 mode is not a writable-file
  # permission and cannot be tightened with chmod, so only apply the mode
  # check to non-symlinks while still requiring every entry to be root-owned.
  violation="$(find "${path}" -xdev \( ! -user root -o \( ! -type l -a -perm /022 \) \) -print -quit)"
  [[ -z "${violation}" ]] || fail "目录必须为 root 所有且不可 group/other 写：${violation}"
}

install_control_plane() {
  local unit
  require_regular_file "${PACKAGE_ROOT}/scripts/start-elf2.sh"
  require_regular_file "${PACKAGE_ROOT}/deploy/anima.env.example"
  require_regular_file "${PACKAGE_ROOT}/deploy/anima-candidate.env.example"
  for unit in anima.service anima-candidate.service anima-cloudflared.service; do
    require_regular_file "${PACKAGE_ROOT}/deploy/systemd/${unit}"
  done

  install -d -m 755 -o root -g root "${CONTROL_ROOT}/scripts" "${CONTROL_ROOT}/deploy/systemd"
  install -m 700 -o root -g root "${PACKAGE_ROOT}/scripts/start-elf2.sh" \
    "${CONTROL_ROOT}/scripts/start-elf2.sh"
  install -m 600 -o root -g root "${PACKAGE_ROOT}/deploy/anima.env.example" \
    "${CONTROL_ROOT}/deploy/anima.env.example"
  install -m 600 -o root -g root "${PACKAGE_ROOT}/deploy/anima-candidate.env.example" \
    "${CONTROL_ROOT}/deploy/anima-candidate.env.example"
  for unit in anima.service anima-candidate.service anima-cloudflared.service; do
    install -m 644 -o root -g root "${PACKAGE_ROOT}/deploy/systemd/${unit}" \
      "${CONTROL_ROOT}/deploy/systemd/${unit}"
    install -m 644 -o root -g root "${CONTROL_ROOT}/deploy/systemd/${unit}" \
      "/etc/systemd/system/${unit}"
  done
  install -m 700 -o root -g root "${CONTROL_ROOT}/scripts/start-elf2.sh" "${LAUNCHER_PATH}"
  verify_root_owned_tree "${CONTROL_ROOT}"
}

prepare_layout() {
  ensure_service_account anima-gateway
  ensure_service_account anima-candidate
  ensure_service_account anima-tunnel

  install -d -m 755 -o root -g root "${INSTALL_ROOT}" "${RELEASES_ROOT}"
  if [[ ! -e "${SOURCE_ROOT}" ]]; then
    install -d -m 750 -o "${DEPLOY_OWNER}" -g "${DEPLOY_OWNER}" "${SOURCE_ROOT}"
  fi
  [[ -d "${SOURCE_ROOT}" && ! -L "${SOURCE_ROOT}" ]] || fail "发布输入目录异常：${SOURCE_ROOT}"
  [[ "$(stat -c '%U' "${SOURCE_ROOT}")" == "${DEPLOY_OWNER}" ]] || \
    fail "发布输入目录必须由 ${DEPLOY_OWNER} 所有：${SOURCE_ROOT}"
  (( (8#$(stat -c '%a' "${SOURCE_ROOT}") & 022) == 0 )) || \
    fail "发布输入目录不得允许 group/other 写入：${SOURCE_ROOT}"

  [[ -d "${MODELS_ROOT}" ]] || fail "缺少模型目录：${MODELS_ROOT}"
  require_regular_tree "${MODELS_ROOT}"
  chown -R root:root "${MODELS_ROOT}"
  chmod -R go-w "${MODELS_ROOT}"

  if [[ ! -d "${RUNTIME_ROOT}" ]]; then
    python3 -m venv "${RUNTIME_ROOT}"
  fi
  [[ -d "${RUNTIME_ROOT}" && ! -L "${RUNTIME_ROOT}" ]] || fail "共享 Python 根目录异常"
  find "${RUNTIME_ROOT}" -xdev -type d -exec chown root:root {} + -exec chmod go-w {} +
  find "${RUNTIME_ROOT}" -xdev -type f -exec chown root:root {} + -exec chmod go-w {} +
  find "${RUNTIME_ROOT}" -xdev -type l -exec chown -h root:root {} +
  verify_root_owned_tree "${RUNTIME_ROOT}"
  [[ -x "${RUNTIME_ROOT}/bin/python" ]] || fail "共享 Python 不可执行"

  install -d -m 755 -o root -g root /opt/anima /opt/anima/current /opt/anima/candidate /opt/anima/runtime /opt/anima/models
  install -d -m 700 -o root -g root "${CONFIG_ROOT}" "${DEPLOY_STATE}"
  install -d -m 700 -o anima-gateway -g anima-gateway /var/lib/anima/memory /var/cache/anima /run/anima
  install -d -m 700 -o anima-candidate -g anima-candidate /var/lib/anima-candidate/memory /var/cache/anima-candidate /run/anima-candidate

  if [[ ! -e "${CONFIG_ROOT}/anima.env" ]]; then
    install -m 600 -o root -g root "${CONTROL_ROOT}/deploy/anima.env.example" "${CONFIG_ROOT}/anima.env"
  fi
  if [[ ! -e "${CONFIG_ROOT}/anima-candidate.env" ]]; then
    install -m 600 -o root -g root "${CONTROL_ROOT}/deploy/anima-candidate.env.example" "${CONFIG_ROOT}/anima-candidate.env"
  fi
}

main() {
  require_root
  require_commands
  install_control_plane
  prepare_layout
  systemctl daemon-reload
  log "控制面已安装。下一步：sudoedit /etc/anima/anima.env；写入 /etc/anima/tunnel-token；上传 source 后运行 sudo ${LAUNCHER_PATH} deploy <release-id>。"
}

main "$@"
