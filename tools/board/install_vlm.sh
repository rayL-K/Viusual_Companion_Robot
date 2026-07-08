#!/usr/bin/env bash
set -Eeuo pipefail

readonly PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
readonly INSTALL_ROOT="/opt/visual-companion-vlm"
readonly VENDOR_ROOT="${INSTALL_ROOT}/vendor"
readonly MODEL_ROOT="${INSTALL_ROOT}/models"
readonly VENDOR_REPOSITORY="https://github.com/Qengineering/Qwen3-VL-2B-NPU.git"
readonly VENDOR_COMMIT="3aa2c11b8a1f3db15a6d4145e4f93840a9a02cb4"
readonly MODEL_SOURCE_DIR="${VISUAL_COMPANION_VLM_MODEL_SOURCE_DIR:-${PROJECT_ROOT}/main/models/vlm}"
readonly LLM_MODEL="qwen3-vl-2b-instruct_w8a8_rk3588.rkllm"
readonly VISION_MODEL="qwen3-vl-2b-vision_rk3588.rknn"
readonly LLM_SHA256="fff51586d0afbc2516b5ab1a5cda2cefaf7fcbea4ee4a1d59cc37e9a08d26c5f"
readonly VISION_SHA256="99ed529107133af2570b521f45da510b6e539054e9952218be55d53c3f9c3bfc"

if [[ ${EUID} -ne 0 ]]; then
  exec sudo --preserve-env=HTTPS_PROXY,HTTP_PROXY,NO_PROXY,VISUAL_COMPANION_VLM_MODEL_SOURCE_DIR -- "$0" "$@"
fi

require_command() {
  command -v "$1" >/dev/null 2>&1 || {
    printf '缺少命令：%s\n' "$1" >&2
    exit 1
  }
}

install_model() {
  local name="$1"
  local checksum="$2"
  local target="${MODEL_ROOT}/${name}"
  if [[ -f ${target} ]] && printf '%s  %s\n' "${checksum}" "${target}" | sha256sum --check --status; then
    printf '模型已存在且校验通过：%s\n' "${name}"
    return
  fi
  local source="${MODEL_SOURCE_DIR}/${name}"
  if [[ ! -f ${source} ]]; then
    printf '缺少经过浏览器下载的 Qwen3-VL 权重：%s\n' "${source}" >&2
    printf '来源见 https://github.com/Qengineering/Qwen3-VL-2B-NPU ，下载后放入 main/models/vlm。\n' >&2
    exit 1
  fi
  printf '%s  %s\n' "${checksum}" "${source}" | sha256sum --check
  install -m 664 -o wenkang -g wenkang "${source}" "${target}.part"
  mv -- "${target}.part" "${target}"
}

require_command git
require_command cmake
require_command sha256sum
install -d -m 755 -o wenkang -g wenkang "${INSTALL_ROOT}" "${MODEL_ROOT}"

if [[ -f ${VENDOR_ROOT}/.source-commit ]] \
  && [[ $(<"${VENDOR_ROOT}/.source-commit") == "${VENDOR_COMMIT}" ]]; then
  printf '使用已预置并固定版本的 VLM 构建源码。\n'
elif [[ ! -d ${VENDOR_ROOT}/.git ]]; then
  rm -rf -- "${VENDOR_ROOT}"
  for attempt in {1..5}; do
    if git -c http.version=HTTP/1.1 clone --depth 1 "${VENDOR_REPOSITORY}" "${VENDOR_ROOT}"; then
      break
    fi
    rm -rf -- "${VENDOR_ROOT}"
    [[ ${attempt} -lt 5 ]] || exit 1
    sleep $((attempt * 2))
  done
  git -C "${VENDOR_ROOT}" -c http.version=HTTP/1.1 fetch --depth 1 origin "${VENDOR_COMMIT}"
  git -C "${VENDOR_ROOT}" checkout --detach "${VENDOR_COMMIT}"
  printf '%s' "${VENDOR_COMMIT}" >"${VENDOR_ROOT}/.source-commit"
else
  git -C "${VENDOR_ROOT}" -c http.version=HTTP/1.1 fetch --depth 1 origin "${VENDOR_COMMIT}"
  git -C "${VENDOR_ROOT}" checkout --detach "${VENDOR_COMMIT}"
  printf '%s' "${VENDOR_COMMIT}" >"${VENDOR_ROOT}/.source-commit"
fi
install -m 644 "${PROJECT_ROOT}/main/native/rk3588_vlm/vlm_worker.cpp" "${VENDOR_ROOT}/src/main.cpp"

cmake -S "${VENDOR_ROOT}" -B "${VENDOR_ROOT}/build" \
  -DRK_LIB_PATH="${VENDOR_ROOT}/aarch64/library" \
  -DCMAKE_CXX_FLAGS="-I${VENDOR_ROOT}/aarch64/include" \
  -DCMAKE_BUILD_TYPE=Release
cmake --build "${VENDOR_ROOT}/build" --parallel 4
install -m 755 "${VENDOR_ROOT}/VLM_NPU" "${INSTALL_ROOT}/vlm_worker"

install_model "${LLM_MODEL}" "${LLM_SHA256}"
install_model "${VISION_MODEL}" "${VISION_SHA256}"
chown -R wenkang:wenkang "${INSTALL_ROOT}"

install -m 644 "${PROJECT_ROOT}/tools/systemd/visual-companion-vlm.service" \
  /etc/systemd/system/visual-companion-vlm.service
install -m 644 "${PROJECT_ROOT}/tools/systemd/visual-companion-control.service" \
  /etc/systemd/system/visual-companion-control.service
systemctl daemon-reload
systemctl enable visual-companion-vlm.service
printf 'RK3588 语义视觉已安装。执行 ~/start-robot restart 启动并自检。\n'
