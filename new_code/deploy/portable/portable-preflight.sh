#!/usr/bin/env bash
# Read-only preflight for an Anima v0.0.1 portable Linux host.
# It deliberately does not install packages, read .env files, or contact APIs.
set -Eeuo pipefail

readonly SCRIPT_NAME="$(basename "$0")"

SOURCE_ROOT=""
DATA_ROOT="/var/lib/anima"
TTS_MODEL_DIR=""
ASR_MODEL_DIR=""
VISION_URL=""
PROFILE="speech"
JSON=false
STRICT=false

ERRORS=0
WARNINGS=0
NOTES=()

usage() {
  cat <<'EOF'
用法：portable-preflight.sh --source <release-input> --tts-model <目录> [选项]

这是只读预检：不会安装软件、读取密钥、修改服务或请求云端 API。

必填：
  --source DIR        含 backend/、web/dist/、config/persona.md 的构建后 release 输入
  --tts-model DIR     当前唯一已实现的 TTS（sherpa-onnx）模型目录

可选：
  --profile NAME      speech（默认）、asr、perception
  --asr-model DIR     sherpa-onnx streaming Zipformer 模型目录；profile=asr/perception 必填
  --vision-url URL    已部署 local-vlm 的 loopback URL；profile=perception 必填
  --data-root DIR     将恢复独立用户数据的文件系统位置（默认 /var/lib/anima）
  --strict            将 Cloudflare/cloudflared、SQLite CLI 等建议项视为失败
  --json              输出机器可读结果（不含任何密钥）
  -h, --help          显示帮助

profile 仅描述当前已实现的 Provider 组合：
  speech      DeepSeek 云端 LLM + 本地 sherpa TTS；ASR/VLM 可禁用。
  asr         speech + 本地 sherpa streaming ASR。
  perception  asr + 已独立部署、仅 loopback 可访问的 local-vlm。
EOF
}

die_usage() {
  printf '错误：%s\n\n' "$*" >&2
  usage >&2
  exit 2
}

note() {
  NOTES+=("$1")
  if [[ "$JSON" == false ]]; then
    printf '%s\n' "$1"
  fi
}

pass() { note "PASS  $*"; }

warn() {
  WARNINGS=$((WARNINGS + 1))
  note "WARN  $*"
}

fail() {
  ERRORS=$((ERRORS + 1))
  note "FAIL  $*"
}

need_value() {
  [[ $# -ge 2 && -n "$2" ]] || die_usage "$1 需要一个值"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --source) need_value "$1" "${2:-}"; SOURCE_ROOT="$2"; shift 2 ;;
    --data-root) need_value "$1" "${2:-}"; DATA_ROOT="$2"; shift 2 ;;
    --tts-model) need_value "$1" "${2:-}"; TTS_MODEL_DIR="$2"; shift 2 ;;
    --asr-model) need_value "$1" "${2:-}"; ASR_MODEL_DIR="$2"; shift 2 ;;
    --vision-url) need_value "$1" "${2:-}"; VISION_URL="$2"; shift 2 ;;
    --profile) need_value "$1" "${2:-}"; PROFILE="$2"; shift 2 ;;
    --strict) STRICT=true; shift ;;
    --json) JSON=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die_usage "未知参数：$1" ;;
  esac
done

case "$PROFILE" in
  speech|asr|perception) ;;
  *) die_usage "--profile 只能是 speech、asr 或 perception" ;;
esac
[[ -n "$SOURCE_ROOT" ]] || die_usage "缺少 --source"
[[ -n "$TTS_MODEL_DIR" ]] || die_usage "缺少 --tts-model；当前运行时没有云端 TTS adapter"
if [[ "$PROFILE" == asr || "$PROFILE" == perception ]]; then
  [[ -n "$ASR_MODEL_DIR" ]] || die_usage "profile=${PROFILE} 需要 --asr-model"
fi
if [[ "$PROFILE" == perception ]]; then
  [[ -n "$VISION_URL" ]] || die_usage "profile=perception 需要 --vision-url"
fi

check_command() {
  local command_name="$1"
  if command -v "$command_name" >/dev/null 2>&1; then
    pass "命令存在：${command_name}"
  elif [[ "$STRICT" == true ]]; then
    fail "缺少建议命令：${command_name}"
  else
    warn "缺少建议命令：${command_name}"
  fi
}

check_required_command() {
  local command_name="$1"
  if command -v "$command_name" >/dev/null 2>&1; then
    pass "命令存在：${command_name}"
  else
    fail "缺少必需命令：${command_name}"
  fi
}

check_model_file() {
  local path="$1"
  local label="$2"
  if [[ -f "$path" ]]; then
    pass "${label}：${path}"
  else
    fail "缺少 ${label}：${path}"
  fi
}

check_source() {
  local source
  source="$(readlink -f -- "$SOURCE_ROOT" 2>/dev/null || true)"
  if [[ -z "$source" || ! -d "$source" ]]; then
    fail "release 输入目录不存在：${SOURCE_ROOT}"
    return
  fi
  SOURCE_ROOT="$source"
  pass "release 输入目录：${SOURCE_ROOT}"
  check_model_file "${SOURCE_ROOT}/backend/pyproject.toml" "backend pyproject"
  check_model_file "${SOURCE_ROOT}/config/persona.md" "默认 Anima 人设"
  check_model_file "${SOURCE_ROOT}/web/dist/index.html" "已构建 Web 入口"
  if find "${SOURCE_ROOT}/web/dist" -type f -name '*.model3.json' -print -quit | grep -q .; then
    pass "构建产物包含 Live2D model3.json"
  else
    fail "web/dist 未发现 Live2D model3.json；不要迁移缺少实际角色资源的构建产物"
  fi
  if [[ -d "${SOURCE_ROOT}/backend/src/veyrasoul" ]]; then
    pass "Gateway 源码目录完整"
  else
    fail "缺少 backend/src/veyrasoul"
  fi
}

check_tts() {
  local root
  root="$(readlink -f -- "$TTS_MODEL_DIR" 2>/dev/null || true)"
  if [[ -z "$root" || ! -d "$root" ]]; then
    fail "TTS 模型目录不存在：${TTS_MODEL_DIR}"
    return
  fi
  pass "sherpa TTS 模型目录：${root}"
  check_model_file "${root}/tokens.txt" "TTS tokens.txt"
  if [[ -f "${root}/model-steps-3.onnx" && -f "${root}/vocos-22khz-univ.onnx" ]]; then
    check_model_file "${root}/lexicon.txt" "Matcha lexicon.txt"
    pass "识别到 Matcha TTS 模型"
  elif [[ -f "${root}/voices.bin" && ( -f "${root}/model.int8.onnx" || -f "${root}/model.onnx" ) ]]; then
    pass "识别到 Kokoro TTS 模型"
  elif [[ -f "${root}/model.int8.onnx" || -f "${root}/vits-aishell3.int8.onnx" || -f "${root}/model.onnx" || -f "${root}/vits-aishell3.onnx" ]]; then
    pass "识别到 VITS TTS 模型"
  else
    fail "未识别出当前 Sherpa TTS adapter 支持的模型文件"
  fi
}

check_asr() {
  local root
  root="$(readlink -f -- "$ASR_MODEL_DIR" 2>/dev/null || true)"
  if [[ -z "$root" || ! -d "$root" ]]; then
    fail "ASR 模型目录不存在：${ASR_MODEL_DIR}"
    return
  fi
  pass "sherpa streaming ASR 模型目录：${root}"
  check_model_file "${root}/tokens.txt" "ASR tokens.txt"
  local component
  for component in encoder decoder joiner; do
    if find "${root}" -maxdepth 1 -type f -iname "${component}*.onnx" -print -quit | grep -q .; then
      pass "ASR ${component} ONNX"
    else
      fail "缺少 ASR ${component}*.onnx"
    fi
  done
}

check_os_and_machine() {
  if [[ -r /etc/os-release ]]; then
    # shellcheck disable=SC1091
    . /etc/os-release
    if [[ "${ID:-}" == ubuntu && ( "${VERSION_ID:-}" == 22.04 || "${VERSION_ID:-}" == 24.04 ) ]]; then
      pass "目标系统：Ubuntu ${VERSION_ID}"
    else
      fail "目标需要 Ubuntu 22.04 或 24.04；当前为 ${PRETTY_NAME:-unknown}"
    fi
  else
    fail "无法读取 /etc/os-release"
  fi

  local arch
  arch="$(uname -m 2>/dev/null || true)"
  case "$arch" in
    x86_64|aarch64) pass "支持的架构：${arch}" ;;
    *) fail "当前只验证 x86_64 / aarch64；检测到 ${arch:-unknown}" ;;
  esac

  local cpu memory_mb
  cpu="$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 0)"
  memory_mb="$(awk '/MemTotal:/ {print int($2 / 1024)}' /proc/meminfo 2>/dev/null || echo 0)"
  if (( cpu >= 4 )); then pass "CPU 线程：${cpu}"; else fail "CPU 线程不足：${cpu}，最低 4"; fi
  if [[ "$PROFILE" == perception ]]; then
    if (( memory_mb >= 16384 )); then pass "内存：${memory_mb} MiB"; else fail "perception profile 需要至少 16 GiB RAM，当前 ${memory_mb} MiB"; fi
  elif (( memory_mb >= 8192 )); then
    pass "内存：${memory_mb} MiB"
  else
    fail "speech/asr profile 需要至少 8 GiB RAM，当前 ${memory_mb} MiB"
  fi
}

check_storage() {
  local parent available_kb
  parent="$DATA_ROOT"
  while [[ ! -d "$parent" && "$parent" != / ]]; do parent="$(dirname -- "$parent")"; done
  available_kb="$(df -Pk "$parent" | awk 'NR == 2 {print $4}')"
  if [[ "$available_kb" =~ ^[0-9]+$ ]] && (( available_kb >= 20971520 )); then
    pass "数据卷可用空间：$((available_kb / 1024 / 1024)) GiB（${parent}）"
  else
    fail "数据卷可用空间不足 20 GiB：${parent}"
  fi
}

check_vision() {
  # Gateway settings intentionally reject non-loopback VLM endpoints to prevent
  # camera frames being sent to an arbitrary remote URL.
  if [[ "$VISION_URL" =~ ^https?://(127\.0\.0\.1|\[::1\]|localhost)(:[0-9]+)?(/|$) ]]; then
    pass "VLM URL 为 loopback：${VISION_URL}"
  else
    fail "当前 local-vlm adapter 只允许 loopback HTTP(S) URL：${VISION_URL}"
  fi
}

emit_json() {
  local status="pass"
  (( ERRORS == 0 )) || status="fail"
  local joined=""
  local item
  for item in "${NOTES[@]}"; do
    item="${item//\\/\\\\}"
    item="${item//\"/\\\"}"
    item="${item//$'\n'/ }"
    [[ -z "$joined" ]] || joined+=","
    joined+="\"${item}\""
  done
  printf '{"status":"%s","profile":"%s","errors":%d,"warnings":%d,"checks":[%s]}\n' \
    "$status" "$PROFILE" "$ERRORS" "$WARNINGS" "$joined"
}

main() {
  check_os_and_machine
  for command_name in bash python3 systemctl sha256sum tar find awk df getconf; do
    check_required_command "$command_name"
  done
  check_command cloudflared
  check_command sqlite3
  check_source
  check_storage
  check_tts
  if [[ "$PROFILE" == asr || "$PROFILE" == perception ]]; then check_asr; fi
  if [[ "$PROFILE" == perception ]]; then check_vision; fi

  if [[ "$JSON" == true ]]; then
    emit_json
  else
    printf '\n结果：%d 项失败，%d 项提醒。\n' "$ERRORS" "$WARNINGS"
    printf '%s\n' '此预检刻意不读取 /etc/anima/*.env；在新主机单独创建密钥与 Tunnel token。'
  fi
  (( ERRORS == 0 ))
}

main "$@"
