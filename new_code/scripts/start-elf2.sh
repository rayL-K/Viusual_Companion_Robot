#!/usr/bin/env bash
set -Eeuo pipefail

# Anima 发布器只管理 /home/wenkang/anima 与 anima*.service，不停止、禁用或改写其他服务。
readonly ACTION="${1:-status}"
readonly REQUESTED_RELEASE_ID="${2:-${ANIMA_RELEASE_ID:-}}"
readonly LAUNCHER_PATH="/usr/local/sbin/anima-deploy"
readonly CONTROL_ROOT="/opt/anima-control"
readonly SOURCE_ROOT="/home/wenkang/anima/source"
readonly INSTALL_ROOT="/home/wenkang/anima"
readonly RELEASES_ROOT="${INSTALL_ROOT}/releases"
readonly SHARED_PYTHON="${INSTALL_ROOT}/.venv/bin/python"
readonly MODELS_ROOT="${INSTALL_ROOT}/models"
readonly DEPLOY_INPUT_OWNER="wenkang"
readonly CURRENT_LINK="${INSTALL_ROOT}/current"
readonly CANDIDATE_LINK="${INSTALL_ROOT}/candidate"
readonly DEPLOY_STATE="/var/lib/anima-deploy"
readonly CANDIDATE_DATA="/var/lib/anima-candidate"
readonly DEPLOY_LOCK="/run/lock/anima-deploy.lock"
readonly HEALTHY_RECORD="${DEPLOY_STATE}/healthy-release"
readonly PREVIOUS_RECORD="${DEPLOY_STATE}/previous-release"
readonly ACTIVE_UNIT="anima.service"
readonly CANDIDATE_UNIT="anima-candidate.service"
readonly TUNNEL_UNIT="anima-cloudflared.service"
readonly ACTIVE_URL="http://127.0.0.1:8875/v2/health"
readonly CANDIDATE_URL="http://127.0.0.1:8876/v2/health"
readonly HEALTH_ATTEMPTS="${ANIMA_HEALTH_ATTEMPTS:-90}"
readonly MIN_AVAILABLE_MB="${ANIMA_MIN_AVAILABLE_MB:-1800}"

INCOMING_PATH=""
INCOMING_ID=""
INCOMING_OWNED=false

log() { printf '[Anima v0.0.1] %s\n' "$*"; }
fail() { log "失败：$*" >&2; exit 1; }

cleanup_incoming() {
  if [[ "${INCOMING_OWNED}" == true && -n "${INCOMING_PATH}" && -d "${INCOMING_PATH}" ]]; then
    case "${INCOMING_PATH}" in
      "${RELEASES_ROOT}"/.*.incoming)
        if [[ "$(stat -c '%d:%i' "${INCOMING_PATH}" 2>/dev/null || true)" == "${INCOMING_ID}" ]]; then
          find "${INCOMING_PATH}" -xdev -depth -delete
        else
          log "拒绝清理 inode 已变化的发布临时目录：${INCOMING_PATH}" >&2
        fi
        ;;
      *) log "拒绝清理非发布临时目录：${INCOMING_PATH}" >&2 ;;
    esac
  fi
}
trap cleanup_incoming EXIT

usage() {
  cat >&2 <<'EOF'
用法：start-elf2.sh <stage|health|activate|deploy|start|restart|status|stop|rollback|plan> [release-id]

  stage      复制白名单制品到不可变 release，不影响当前服务
  health     在 8876 端口启动候选版本并通过 /v2/health
  activate   仅激活已记录为健康的候选版本，失败自动恢复
  deploy     按 stage -> health -> activate 顺序执行
  rollback   原子切回上一个已激活 release
EOF
  exit 2
}

require_root() {
  [[ ${EUID} -eq 0 ]] || fail "请通过固定入口运行：sudo ${LAUNCHER_PATH} $*"
}

require_commands() {
  local command_name
  for command_name in awk basename chmod chown cmp cp curl date dirname find flock getent grep groupadd head id \
    install journalctl ln mv readlink rm sed sha256sum sleep sort ss stat systemctl useradd wc xargs; do
    command -v "${command_name}" >/dev/null 2>&1 || fail "缺少命令：${command_name}"
  done
}

verify_control_plane() {
  local actual_launcher control_violation
  actual_launcher="$(readlink -f -- "$0" 2>/dev/null || true)"
  [[ "${actual_launcher}" == "${LAUNCHER_PATH}" ]] || \
    fail "拒绝以 root 运行非固定入口：${actual_launcher:-unknown}"
  [[ -f "${LAUNCHER_PATH}" && ! -L "${LAUNCHER_PATH}" ]] || fail "固定 launcher 缺失或是符号链接"
  [[ "$(stat -c '%U' "${LAUNCHER_PATH}")" == root ]] || fail "固定 launcher 必须由 root 所有"
  (( (8#$(stat -c '%a' "${LAUNCHER_PATH}") & 022) == 0 )) || fail "固定 launcher 不能允许 group/other 写入"

  [[ -d "${CONTROL_ROOT}" && ! -L "${CONTROL_ROOT}" ]] || fail "缺少 root-owned 控制包：${CONTROL_ROOT}"
  control_violation="$(find "${CONTROL_ROOT}" -xdev \( -type l -o ! -user root \) -print -quit)"
  [[ -z "${control_violation}" ]] || fail "控制包含符号链接或非 root 所有项：${control_violation}"
  control_violation="$(find "${CONTROL_ROOT}" -xdev ! -type l -perm /022 -print -quit)"
  [[ -z "${control_violation}" ]] || fail "控制包含 group/other 可写项：${control_violation}"
  cmp -s "${LAUNCHER_PATH}" "${CONTROL_ROOT}/scripts/start-elf2.sh" || \
    fail "固定 launcher 与 root-owned 控制脚本不一致"

  local unit_name installed_unit trusted_unit
  for unit_name in "${ACTIVE_UNIT}" "${CANDIDATE_UNIT}" "${TUNNEL_UNIT}"; do
    installed_unit="/etc/systemd/system/${unit_name}"
    trusted_unit="${CONTROL_ROOT}/deploy/systemd/${unit_name}"
    [[ -f "${installed_unit}" && ! -L "${installed_unit}" ]] || fail "缺少预安装 unit：${installed_unit}"
    [[ "$(stat -c '%U' "${installed_unit}")" == root ]] || fail "预安装 unit 必须由 root 所有：${unit_name}"
    (( (8#$(stat -c '%a' "${installed_unit}") & 022) == 0 )) || fail "预安装 unit 可被非 root 修改：${unit_name}"
    cmp -s "${installed_unit}" "${trusted_unit}" || fail "预安装 unit 与控制包不一致：${unit_name}"
  done
}

acquire_mutation_lock() {
  command -v flock >/dev/null 2>&1 || fail "缺少命令：flock"
  exec 9>"${DEPLOY_LOCK}"
  flock -n 9 || fail "另一个 Anima 发布操作正在运行，请稍后重试"
  chown root:root "${DEPLOY_LOCK}"
  chmod 600 "${DEPLOY_LOCK}"
}

validate_positive_integer() {
  local name="$1"
  local value="$2"
  [[ "${value}" =~ ^[1-9][0-9]*$ ]] || fail "${name} 必须是正整数"
}

validate_release_id() {
  local release_id="$1"
  [[ "${release_id}" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$ ]] || \
    fail "release-id 只能包含字母、数字、点、下划线和连字符，最长 64 字符"
}

assert_release_path() {
  local path="$1"
  case "${path}" in
    "${RELEASES_ROOT}"/*) ;;
    *) fail "发布路径越界：${path}" ;;
  esac
}

require_service_accounts() {
  getent group anima-gateway >/dev/null 2>&1 || groupadd --system anima-gateway
  id -u anima-gateway >/dev/null 2>&1 || \
    useradd --system --gid anima-gateway --home-dir /nonexistent --shell /usr/sbin/nologin anima-gateway
  getent group anima-candidate >/dev/null 2>&1 || groupadd --system anima-candidate
  id -u anima-candidate >/dev/null 2>&1 || \
    useradd --system --gid anima-candidate --home-dir /nonexistent --shell /usr/sbin/nologin anima-candidate
  getent group anima-tunnel >/dev/null 2>&1 || groupadd --system anima-tunnel
  id -u anima-tunnel >/dev/null 2>&1 || \
    useradd --system --gid anima-tunnel --home-dir /nonexistent --shell /usr/sbin/nologin anima-tunnel
}

prepare_directories() {
  install -d -m 755 -o root -g root "${INSTALL_ROOT}" "${RELEASES_ROOT}"
  install -d -m 755 -o root -g root /opt/anima /opt/anima/current /opt/anima/candidate /opt/anima/runtime /opt/anima/models
  verify_secure_directory "${INSTALL_ROOT}" root
  verify_secure_directory "${RELEASES_ROOT}" root
  verify_secure_directory "${MODELS_ROOT}" root
  install -d -m 700 -o root -g root /etc/anima "${DEPLOY_STATE}"
  install -d -m 700 -o anima-gateway -g anima-gateway /var/lib/anima/memory /var/cache/anima /run/anima
  install -d -m 700 -o anima-candidate -g anima-candidate \
    "${CANDIDATE_DATA}" "${CANDIDATE_DATA}/memory" /var/cache/anima-candidate /run/anima-candidate
}

prepare_host() {
  require_commands
  verify_control_plane
  validate_positive_integer ANIMA_HEALTH_ATTEMPTS "${HEALTH_ATTEMPTS}"
  validate_positive_integer ANIMA_MIN_AVAILABLE_MB "${MIN_AVAILABLE_MB}"
  require_service_accounts
  prepare_directories
}

require_private_file() {
  local path="$1"
  local label="$2"
  [[ -f "${path}" ]] || fail "缺少 ${label}：${path}"
  [[ ! -L "${path}" ]] || fail "${label} 不能是符号链接"
  local mode
  mode="$(stat -c '%a' "${path}")"
  (( (8#${mode} & 077) == 0 )) || fail "${label} 必须禁止 group/other 读写（建议 600）"
  [[ "$(stat -c '%U' "${path}")" == root ]] || fail "${label} 必须由 root 所有"
}

require_runtime_config() {
  local config_path="/etc/anima/anima.env"
  require_private_file "${config_path}" "Anima 环境文件"
  if grep -Eq '^[[:space:]]*(ANIMA_HOST|ANIMA_PORT|ANIMA_WEB_DIST|ANIMA_DATA_ROOT|ANIMA_MEMORY_PATH|ANIMA_PERSONA_PATH|ANIMA_ADMISSION_REQUIRED|ANIMA_ALLOWED_ORIGINS|PYTHONPATH)[[:space:]]*=' "${config_path}"; then
    fail "Anima 环境文件包含部署保留键；请移除 host/port/web/data/memory/persona/admission/origins/PYTHONPATH 定义"
  fi
  require_nonempty_env_value "${config_path}" ANIMA_LLM_API_KEY
  require_secret_value "${config_path}" ANIMA_ADMISSION_SECRET
  require_secret_value "${config_path}" ANIMA_TELEMETRY_HMAC_KEY
  require_nonempty_env_value "${config_path}" ANIMA_TURNSTILE_SITE_KEY
  require_nonempty_env_value "${config_path}" ANIMA_TURNSTILE_SECRET
}

require_candidate_config() {
  local config_path="/etc/anima/anima-candidate.env"
  require_private_file "${config_path}" "Anima candidate 环境文件"
  if grep -Eq '^[[:space:]]*(ANIMA_HOST|ANIMA_PORT|ANIMA_WEB_DIST|ANIMA_DATA_ROOT|ANIMA_MEMORY_PATH|ANIMA_PERSONA_PATH|ANIMA_LLM_API_KEY|ANIMA_ADMISSION_REQUIRED|ANIMA_ADMISSION_SECRET|ANIMA_ALLOWED_ORIGINS|ANIMA_TELEMETRY_HMAC_KEY|ANIMA_TURNSTILE_SECRET|ANIMA_TURNSTILE_SITE_KEY|PYTHONPATH)[[:space:]]*=' "${config_path}"; then
    fail "Candidate 环境文件包含路径或密钥保留键"
  fi
}

require_secret_value() {
  local config_path="$1"
  local key="$2"
  local value
  if ! value="$(awk -v key="${key}" '
    BEGIN { count = 0 }
    {
      line = $0
      sub(/\r$/, "", line)
      if (line ~ "^[[:space:]]*" key "[[:space:]]*=") {
        count++
        sub("^[[:space:]]*" key "[[:space:]]*=", "", line)
        sub(/^[[:space:]]+/, "", line)
        sub(/[[:space:]]+$/, "", line)
        value = line
      }
    }
    END {
      if (count != 1) exit 2
      print value
    }
  ' "${config_path}")"; then
    fail "Anima 环境文件必须且只能定义一次 ${key}"
  fi
  case "${value}" in
    \"*|\'*) fail "${key} 必须使用单行无引号值" ;;
  esac
  [[ "${value}" =~ ^[A-Za-z0-9._~+/=-]{32,}$ ]] || fail "${key} 必须是至少 32 字节的随机 ASCII 值"
}

require_nonempty_env_value() {
  local config_path="$1"
  local key="$2"
  local value
  if ! value="$(awk -v key="${key}" '
    BEGIN { count = 0 }
    {
      line = $0
      sub(/\r$/, "", line)
      if (line ~ "^[[:space:]]*" key "[[:space:]]*=") {
        count++
        sub("^[[:space:]]*" key "[[:space:]]*=", "", line)
        sub(/^[[:space:]]+/, "", line)
        sub(/[[:space:]]+$/, "", line)
        value = line
      }
    }
    END {
      if (count != 1 || value == "") exit 2
      print value
    }
  ' "${config_path}")"; then
    fail "Anima 环境文件必须且只能定义一次非空 ${key}"
  fi
  case "${value}" in
    *[[:space:]]*|\"*|\'*|*=*) fail "${key} 必须使用单行无空白值" ;;
  esac
}

prepare_tunnel_token() {
  require_private_file /etc/anima/tunnel-token "Anima 专用 Tunnel token"
}

verify_shared_runtime() {
  local runtime_root="${INSTALL_ROOT}/.venv"
  local violation

  [[ -d "${runtime_root}" ]] || fail "缺少共享 Linux 运行时：${runtime_root}"
  [[ ! -L "${runtime_root}" ]] || fail "共享 Linux 运行时根目录不能是符号链接"
  [[ -x "${SHARED_PYTHON}" ]] || fail "共享 Python 不可执行：${SHARED_PYTHON}"
  violation="$(find "${runtime_root}" -xdev ! -user root -print -quit)"
  [[ -z "${violation}" ]] || fail "共享 Linux 运行时必须完整归 root 所有：${violation}"
  violation="$(find "${runtime_root}" -xdev ! -type l -perm /022 -print -quit)"
  [[ -z "${violation}" ]] || fail "共享 Linux 运行时含 group/other 可写项：${violation}"
}

verify_secure_directory() {
  local path="$1"
  local expected_owner="$2"
  [[ -d "${path}" && ! -L "${path}" ]] || fail "安全目录缺失或是符号链接：${path}"
  [[ "$(stat -c '%U' "${path}")" == "${expected_owner}" ]] || fail "安全目录所有者异常：${path}"
  (( (8#$(stat -c '%a' "${path}") & 022) == 0 )) || fail "安全目录禁止 group/other 写入：${path}"
}

verify_deploy_input() {
  verify_secure_directory "${SOURCE_ROOT}" "${DEPLOY_INPUT_OWNER}"
  [[ -d "${SOURCE_ROOT}/backend" && ! -L "${SOURCE_ROOT}/backend" ]] || fail "source backend 目录异常"
  [[ -d "${SOURCE_ROOT}/web" && ! -L "${SOURCE_ROOT}/web" ]] || fail "source web 目录异常"
  [[ -d "${SOURCE_ROOT}/config" && ! -L "${SOURCE_ROOT}/config" ]] || fail "source config 目录异常"
}

assert_regular_tree() {
  local path="$1"
  local label="$2"
  local violation
  [[ -e "${path}" && ! -L "${path}" ]] || fail "缺少或链接化的 ${label}：${path}"
  violation="$(find "${path}" -xdev \( -type l -o \( ! -type f -a ! -type d \) \) -print -quit)"
  [[ -z "${violation}" ]] || fail "${label} 只允许普通文件和目录：${violation}"
}

verify_source_artifacts() {
  verify_deploy_input
  [[ -d "${SOURCE_ROOT}/backend/src" ]] || fail "缺少 backend/src"
  [[ -f "${SOURCE_ROOT}/backend/pyproject.toml" && ! -L "${SOURCE_ROOT}/backend/pyproject.toml" ]] || fail "缺少或链接化的 backend/pyproject.toml"
  [[ -f "${SOURCE_ROOT}/web/dist/index.html" ]] || fail "缺少 web/dist/index.html"
  [[ -f "${SOURCE_ROOT}/config/persona.md" && ! -L "${SOURCE_ROOT}/config/persona.md" ]] || fail "缺少或链接化的 config/persona.md"
  assert_regular_tree "${SOURCE_ROOT}/backend/src" "backend/src"
  assert_regular_tree "${SOURCE_ROOT}/web/dist" "web/dist"
  verify_shared_runtime
}

verify_release() {
  local release_path="$1"
  assert_release_path "${release_path}"
  [[ "$(readlink -f -- "${release_path}")" == "${release_path}" ]] || \
    fail "release 路径必须是规范的直接子目录：${release_path}"
  verify_shared_runtime
  [[ -d "${release_path}/backend/src" ]] || fail "release 缺少后端源码"
  [[ -f "${release_path}/web/dist/index.html" ]] || fail "release 缺少前端制品"
  [[ -f "${release_path}/config/persona.md" ]] || fail "release 缺少角色配置"
  [[ -f "${release_path}/.release.sha256" ]] || fail "release 缺少完整性清单"
  assert_regular_tree "${release_path}" "release"
  local release_violation
  release_violation="$(find "${release_path}" -xdev \( ! -user root -o -perm /022 \) -print -quit)"
  [[ -z "${release_violation}" ]] || fail "release 所有者或权限异常：${release_violation}"
  (cd "${release_path}" && sha256sum --quiet -c .release.sha256) || fail "release 完整性校验失败"
}

atomic_symlink() {
  local target="$1"
  local link_path="$2"
  local next_link="${link_path}.next.$$"
  assert_release_path "${target}"
  [[ ! -e "${link_path}" || -L "${link_path}" ]] || fail "原子指针目标不是符号链接：${link_path}"
  [[ ! -e "${next_link}" && ! -L "${next_link}" ]] || fail "原子指针临时名已存在：${next_link}"
  ln -s "${target}" "${next_link}"
  mv -Tf "${next_link}" "${link_path}"
}

write_state_record() {
  local path="$1"
  local value="$2"
  local temporary="${path}.next.$$"
  [[ "$(dirname -- "${path}")" == "${DEPLOY_STATE}" ]] || fail "部署状态路径越界：${path}"
  [[ ! -e "${path}" || ! -L "${path}" ]] || fail "部署状态记录不能是符号链接：${path}"
  [[ ! -e "${temporary}" && ! -L "${temporary}" ]] || fail "部署状态临时文件已存在：${temporary}"
  printf '%s\n' "${value}" >"${temporary}"
  chown root:root "${temporary}"
  chmod 600 "${temporary}"
  mv -f "${temporary}" "${path}"
}

read_state_record() {
  local path="$1"
  [[ "$(dirname -- "${path}")" == "${DEPLOY_STATE}" ]] || fail "部署状态路径越界：${path}"
  [[ -f "${path}" && ! -L "${path}" ]] || return 0
  [[ "$(stat -c '%U' "${path}")" == root ]] || fail "部署状态记录所有者异常：${path}"
  (( (8#$(stat -c '%a' "${path}") & 077) == 0 )) || fail "部署状态记录权限异常：${path}"
  local content
  content="$(head -n 1 "${path}")"
  [[ "$(wc -l <"${path}")" -eq 1 ]] || fail "部署状态记录格式异常：${path}"
  printf '%s' "${content}"
}

stage_release() {
  local release_id="${REQUESTED_RELEASE_ID:-$(date -u +%Y%m%dT%H%M%SZ)}"
  validate_release_id "${release_id}"
  verify_source_artifacts

  local release_path="${RELEASES_ROOT}/${release_id}"
  assert_release_path "${release_path}"
  [[ ! -e "${release_path}" ]] || fail "release 已存在，不会覆盖：${release_id}"

  INCOMING_PATH="${RELEASES_ROOT}/.${release_id}.incoming"
  [[ ! -e "${INCOMING_PATH}" ]] || fail "发布临时目录已存在，请检查上次失败：${INCOMING_PATH}"
  install -d -m 755 -o root -g root \
    "${INCOMING_PATH}/backend" "${INCOMING_PATH}/web" "${INCOMING_PATH}/config"
  INCOMING_ID="$(stat -c '%d:%i' "${INCOMING_PATH}")"
  INCOMING_OWNED=true

  cp -a "${SOURCE_ROOT}/backend/src" "${INCOMING_PATH}/backend/src"
  cp -a "${SOURCE_ROOT}/backend/pyproject.toml" "${INCOMING_PATH}/backend/pyproject.toml"
  cp -a "${SOURCE_ROOT}/web/dist" "${INCOMING_PATH}/web/dist"
  cp -a "${SOURCE_ROOT}/config/persona.md" "${INCOMING_PATH}/config/persona.md"

  (
    cd "${INCOMING_PATH}"
    find . -type f ! -name .release.sha256 -print0 | sort -z | xargs -0 sha256sum >.release.sha256
  )
  chown -R root:root "${INCOMING_PATH}"
  chmod -R a+rX "${INCOMING_PATH}"
  chmod -R go-w "${INCOMING_PATH}"
  mv "${INCOMING_PATH}" "${release_path}"
  INCOMING_OWNED=false
  INCOMING_ID=""
  INCOMING_PATH=""

  verify_release "${release_path}"
  systemctl stop "${CANDIDATE_UNIT}" 2>/dev/null || true
  reset_candidate_data
  atomic_symlink "${release_path}" "${CANDIDATE_LINK}"
  write_state_record "${HEALTHY_RECORD}" ""
  log "已 staging release ${release_id}；当前服务未变更"
}

require_candidate_headroom() {
  [[ -r /proc/meminfo ]] || return 0
  local available_kb
  available_kb="$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)"
  [[ "${available_kb}" =~ ^[0-9]+$ ]] || fail "无法读取 MemAvailable"
  if (( available_kb < MIN_AVAILABLE_MB * 1024 )); then
    fail "可用内存不足 ${MIN_AVAILABLE_MB} MiB，拒绝启动并行候选实例"
  fi
}

reset_candidate_data() {
  [[ "${CANDIDATE_DATA}" == /var/lib/anima-candidate ]] || fail "candidate 数据路径异常"
  [[ -d "${CANDIDATE_DATA}" && ! -L "${CANDIDATE_DATA}" ]] || fail "candidate 数据目录缺失或为符号链接"
  find "${CANDIDATE_DATA}" -xdev -mindepth 1 -depth -delete
  install -d -m 700 -o anima-candidate -g anima-candidate "${CANDIDATE_DATA}/memory"
}

listener_owned_by_unit() {
  local unit="$1"
  local port="$2"
  local main_pid listeners
  main_pid="$(systemctl show --property MainPID --value "${unit}" 2>/dev/null || true)"
  [[ "${main_pid}" =~ ^[1-9][0-9]*$ ]] || return 1
  listeners="$(ss -H -ltnp "sport = :${port}" 2>/dev/null || true)"
  grep -Eq "pid=${main_pid}," <<<"${listeners}"
}

release_digest() {
  local release_path="$1"
  sha256sum "${release_path}/.release.sha256" | awk '{print $1}'
}

health_ready() {
  local unit="$1"
  local url="$2"
  local port="$3"
  local release_path="$4"
  local expected_digest
  expected_digest="$(release_digest "${release_path}")"
  local response=""
  local attempt
  for ((attempt = 1; attempt <= HEALTH_ATTEMPTS; attempt++)); do
    if systemctl is-active --quiet "${unit}" && listener_owned_by_unit "${unit}" "${port}"; then
      if response="$(curl -fsS --max-time 2 --max-filesize 65536 "${url}" 2>/dev/null)" && \
        printf '%s' "${response}" | EXPECTED_RELEASE_DIGEST="${expected_digest}" "${SHARED_PYTHON}" -c '
import json
import os
import sys

try:
    payload = json.load(sys.stdin)
except (json.JSONDecodeError, UnicodeDecodeError):
    raise SystemExit(1)
valid = (
    isinstance(payload, dict)
    and payload.get("ok") is True
    and payload.get("protocol") == 2
    and payload.get("service") == "anima-gateway"
    and payload.get("releaseDigest") == os.environ["EXPECTED_RELEASE_DIGEST"]
)
raise SystemExit(0 if valid else 1)
' >/dev/null 2>&1; then
        return 0
      fi
    fi
    sleep 1
  done
  journalctl -u "${unit}" -n 80 --no-pager || true
  return 1
}

health_candidate() {
  local candidate_path
  candidate_path="$(readlink -f "${CANDIDATE_LINK}" 2>/dev/null || true)"
  [[ -n "${candidate_path}" ]] || fail "没有 staged candidate"
  verify_release "${candidate_path}"
  require_runtime_config
  require_candidate_config
  require_candidate_headroom

  systemctl stop "${CANDIDATE_UNIT}" 2>/dev/null || true
  reset_candidate_data
  systemctl start "${CANDIDATE_UNIT}"
  if ! health_ready "${CANDIDATE_UNIT}" "${CANDIDATE_URL}" 8876 "${candidate_path}"; then
    systemctl stop "${CANDIDATE_UNIT}" || true
    reset_candidate_data
    write_state_record "${HEALTHY_RECORD}" ""
    fail "候选版本未通过健康检查，当前服务未变更"
  fi
  write_state_record "${HEALTHY_RECORD}" "${candidate_path}"
  log "候选版本已在 127.0.0.1:8876 通过健康检查"
}

restore_after_failed_activation() {
  local previous_path="$1"
  systemctl stop "${TUNNEL_UNIT}" "${ACTIVE_UNIT}" 2>/dev/null || true
  if [[ -n "${previous_path}" ]]; then
    verify_release "${previous_path}"
    atomic_symlink "${previous_path}" "${CURRENT_LINK}"
    systemctl start "${ACTIVE_UNIT}"
    if health_ready "${ACTIVE_UNIT}" "${ACTIVE_URL}" 8875 "${previous_path}"; then
      systemctl start "${TUNNEL_UNIT}" || \
        log "严重：原 release 已恢复，但 Tunnel 未启动" >&2
    else
      log "严重：原 release 也未恢复健康，请查看 journalctl -u ${ACTIVE_UNIT}" >&2
    fi
  else
    [[ ! -L "${CURRENT_LINK}" ]] || rm -f -- "${CURRENT_LINK}"
  fi
}

activate_candidate() {
  local candidate_path healthy_path previous_path
  candidate_path="$(readlink -f "${CANDIDATE_LINK}" 2>/dev/null || true)"
  healthy_path="$(read_state_record "${HEALTHY_RECORD}")"
  [[ -n "${candidate_path}" && "${healthy_path}" == "${candidate_path}" ]] || \
    fail "候选版本没有通过当前健康门，请先执行 health"
  verify_release "${candidate_path}"
  systemctl is-active --quiet "${CANDIDATE_UNIT}" || fail "候选服务已停止，请重新执行 health"
  health_ready "${CANDIDATE_UNIT}" "${CANDIDATE_URL}" 8876 "${candidate_path}" || fail "候选服务已不健康，拒绝激活"

  previous_path="$(readlink -f "${CURRENT_LINK}" 2>/dev/null || true)"
  [[ -z "${previous_path}" ]] || verify_release "${previous_path}"
  write_state_record "${PREVIOUS_RECORD}" "${previous_path}"
  prepare_tunnel_token

  # 先验证再停候选，避免 RK3588 在激活时同时常驻两套模型。
  systemctl stop "${CANDIDATE_UNIT}"
  reset_candidate_data
  atomic_symlink "${candidate_path}" "${CURRENT_LINK}"
  systemctl enable "${ACTIVE_UNIT}" "${TUNNEL_UNIT}" >/dev/null
  systemctl restart "${ACTIVE_UNIT}"
  if ! health_ready "${ACTIVE_UNIT}" "${ACTIVE_URL}" 8875 "${candidate_path}"; then
    restore_after_failed_activation "${previous_path}"
    fail "新 release 激活失败，已恢复上一版"
  fi
  if ! systemctl restart "${TUNNEL_UNIT}" || ! systemctl is-active --quiet "${TUNNEL_UNIT}"; then
    restore_after_failed_activation "${previous_path}"
    fail "Anima Tunnel 启动失败，已恢复上一版"
  fi
  write_state_record "${HEALTHY_RECORD}" ""
  log "已激活 $(basename "${candidate_path}")：https://anima.veyralux.org"
}

start_active() {
  local current_path
  current_path="$(readlink -f "${CURRENT_LINK}" 2>/dev/null || true)"
  [[ -n "${current_path}" ]] || fail "没有已激活 release，请先执行 deploy"
  verify_release "${current_path}"
  require_runtime_config
  prepare_tunnel_token
  systemctl stop "${CANDIDATE_UNIT}" 2>/dev/null || true
  reset_candidate_data
  systemctl enable "${ACTIVE_UNIT}" "${TUNNEL_UNIT}" >/dev/null
  systemctl stop "${TUNNEL_UNIT}" 2>/dev/null || true
  systemctl restart "${ACTIVE_UNIT}"
  health_ready "${ACTIVE_UNIT}" "${ACTIVE_URL}" 8875 "${current_path}" || fail "Anima Gateway 未通过健康检查"
  systemctl restart "${TUNNEL_UNIT}"
  systemctl is-active --quiet "${TUNNEL_UNIT}" || fail "Anima Tunnel 未运行"
  log "Anima 已启动：https://anima.veyralux.org"
}

rollback_release() {
  local target current_before
  target="$(read_state_record "${PREVIOUS_RECORD}")"
  [[ -n "${target}" ]] || fail "没有可回滚的上一个 release"
  verify_release "${target}"
  current_before="$(readlink -f "${CURRENT_LINK}" 2>/dev/null || true)"
  prepare_tunnel_token

  systemctl stop "${CANDIDATE_UNIT}" "${TUNNEL_UNIT}" 2>/dev/null || true
  reset_candidate_data
  atomic_symlink "${target}" "${CURRENT_LINK}"
  systemctl restart "${ACTIVE_UNIT}"
  if ! health_ready "${ACTIVE_UNIT}" "${ACTIVE_URL}" 8875 "${target}"; then
    if [[ -n "${current_before}" ]]; then
      atomic_symlink "${current_before}" "${CURRENT_LINK}"
      systemctl restart "${ACTIVE_UNIT}" || true
      if health_ready "${ACTIVE_UNIT}" "${ACTIVE_URL}" 8875 "${current_before}"; then
        systemctl start "${TUNNEL_UNIT}" || true
      fi
    fi
    fail "回滚目标未通过健康检查，已尝试恢复切换前 release"
  fi
  systemctl restart "${TUNNEL_UNIT}"
  systemctl is-active --quiet "${TUNNEL_UNIT}" || fail "回滚后 Tunnel 未运行"
  write_state_record "${PREVIOUS_RECORD}" "${current_before}"
  log "已回滚到 $(basename "${target}")"
}

show_status() {
  printf 'current=%s\n' "$(readlink -f "${CURRENT_LINK}" 2>/dev/null || printf 'none')"
  printf 'candidate=%s\n' "$(readlink -f "${CANDIDATE_LINK}" 2>/dev/null || printf 'none')"
  systemctl --no-pager --full status "${ACTIVE_UNIT}" "${CANDIDATE_UNIT}" "${TUNNEL_UNIT}" 2>/dev/null |
    sed -n -E '/^\u25cf|Active:|Main PID:/p' || true
}

show_plan() {
  cat <<EOF
product=Anima v0.0.1
source=${SOURCE_ROOT}
control=${CONTROL_ROOT}
entrypoint=${LAUNCHER_PATH}
runtime=${INSTALL_ROOT}/.venv
staging=${CANDIDATE_LINK} -> 127.0.0.1:8876
active=${CURRENT_LINK} -> 127.0.0.1:8875
data=/var/lib/anima
public=https://anima.veyralux.org
remote_config_tunnel=anima.veyralux.org -> http://127.0.0.1:8875
sequence=stage -> health -> activate; rollback uses previous-release
isolation=only /home/wenkang/anima, /etc/anima, /var/lib/anima and anima*.service
EOF
}

case "${ACTION}" in
  plan)
    show_plan
    ;;
  status)
    require_root "$@"
    require_commands
    verify_control_plane
    show_status
    ;;
  stage)
    require_root "$@"
    acquire_mutation_lock
    prepare_host
    require_runtime_config
    stage_release
    ;;
  health)
    require_root "$@"
    acquire_mutation_lock
    prepare_host
    health_candidate
    ;;
  activate)
    require_root "$@"
    acquire_mutation_lock
    prepare_host
    require_runtime_config
    activate_candidate
    ;;
  deploy)
    require_root "$@"
    acquire_mutation_lock
    prepare_host
    require_runtime_config
    stage_release
    health_candidate
    activate_candidate
    ;;
  start|restart)
    require_root "$@"
    acquire_mutation_lock
    prepare_host
    start_active
    ;;
  stop)
    require_root "$@"
    acquire_mutation_lock
    require_commands
    verify_control_plane
    systemctl stop "${CANDIDATE_UNIT}" "${TUNNEL_UNIT}" "${ACTIVE_UNIT}"
    [[ ! -d "${CANDIDATE_DATA}" ]] || reset_candidate_data
    log "只停止了 Anima 服务"
    ;;
  rollback)
    require_root "$@"
    acquire_mutation_lock
    prepare_host
    require_runtime_config
    rollback_release
    ;;
  *) usage ;;
esac
