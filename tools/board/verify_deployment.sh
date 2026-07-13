#!/usr/bin/env bash
set -Eeuo pipefail

readonly SERVICES=(
  visual-companion-emotion.service
  visual-companion-vlm.service
  visual-companion-control.service
  visual-companion-cloudflared.service
)
readonly LOCAL_BASE="http://127.0.0.1:8765"
readonly PUBLIC_BASE="https://anima.veyralux.org"
readonly VOX_MODEL="/opt/visual-companion-voxcpm/models/voxcpm1.5-q4_k-audiovae-f16.gguf"
readonly VOX_SHA256="ce5edb331e869d89a8f816c9288fba4c1cffa636099808d240974a34f2ce8361"

pass() { printf '[PASS] %s\n' "$*"; }
fail() { printf '[FAIL] %s\n' "$*" >&2; exit 1; }

for service in "${SERVICES[@]}"; do
  systemctl is-active --quiet "${service}" || fail "服务未运行：${service}"
  pass "服务运行：${service}"
done

systemctl cat visual-companion-voxcpm.service >/dev/null 2>&1 \
  && fail "检测到已废弃的常驻 VoxCPM 单元"
pgrep -x voxcpm-server >/dev/null 2>&1 \
  && fail "空闲状态仍有 voxcpm-server 进程"
pass "VoxCPM 仅按请求运行"

for endpoint in \
  /health \
  /emotion-health \
  /vision-health \
  /asr-health \
  '/tts-health?voice=matcha_baker' \
  '/tts-health?voice=voxcpm_board'; do
  curl --fail --silent --show-error --max-time 20 "${LOCAL_BASE}${endpoint}" >/dev/null \
    || fail "本地接口失败：${endpoint}"
  pass "本地接口：${endpoint}"
done

[[ -f ${VOX_MODEL} ]] || fail "VoxCPM 模型不存在：${VOX_MODEL}"
printf '%s  %s\n' "${VOX_SHA256}" "${VOX_MODEL}" | sha256sum --check --status \
  || fail "VoxCPM 模型校验失败"
pass "VoxCPM 模型 SHA-256 正确"

curl --fail --silent --show-error --max-time 30 "${PUBLIC_BASE}/health" >/dev/null \
  || fail "正式公网入口未回源到本机"
pass "正式公网入口：${PUBLIC_BASE}"

printf '\nELF2 部署验收通过。\n'
free -h
systemctl --no-pager --full status "${SERVICES[@]}" | sed -n -E '/^●|Active:|Main PID:/p' || true
