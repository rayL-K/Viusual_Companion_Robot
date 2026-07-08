#!/usr/bin/env bash
set -Eeuo pipefail

readonly VOXCPM_COMMIT="6d84d9e4fd23785f0b943722ff354863cda52497"
readonly MODEL_NAME="voxcpm1.5-q4_k-audiovae-f16.gguf"
readonly MODEL_SHA256="ce5edb331e869d89a8f816c9288fba4c1cffa636099808d240974a34f2ce8361"
readonly MODEL_URL="https://huggingface.co/bluryar/VoxCPM-GGUF/resolve/main/${MODEL_NAME}?download=true"
readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"
readonly CACHE_ROOT="${VOXCPM_BUILD_ROOT:-${HOME}/.cache/visual-companion-voxcpm}"
readonly INSTALL_ROOT="/opt/visual-companion-voxcpm"

[[ ${EUID} -ne 0 ]] || { printf '请以普通用户运行，脚本会在安装阶段调用 sudo。\n' >&2; exit 2; }
for command in cmake g++ git curl sha256sum tar; do
  command -v "${command}" >/dev/null || { printf '缺少命令：%s\n' "${command}" >&2; exit 2; }
done

mkdir -p "${CACHE_ROOT}/models"
if [[ -n ${VOXCPM_SOURCE_ARCHIVE:-} ]]; then
  [[ -n ${VOXCPM_SOURCE_SHA256:-} ]] || { printf '使用 VOXCPM_SOURCE_ARCHIVE 时必须同时提供 VOXCPM_SOURCE_SHA256。\n' >&2; exit 2; }
  printf '%s  %s\n' "${VOXCPM_SOURCE_SHA256}" "${VOXCPM_SOURCE_ARCHIVE}" | sha256sum --check
  rm -rf "${CACHE_ROOT}/source"
  mkdir -p "${CACHE_ROOT}/source"
  tar -xzf "${VOXCPM_SOURCE_ARCHIVE}" -C "${CACHE_ROOT}/source" --strip-components=1
elif [[ ! -d "${CACHE_ROOT}/source/.git" ]]; then
  git clone --filter=blob:none https://github.com/bluryar/VoxCPM.cpp.git "${CACHE_ROOT}/source"
fi
if [[ -d "${CACHE_ROOT}/source/.git" ]]; then
  git -C "${CACHE_ROOT}/source" fetch --depth 1 origin "${VOXCPM_COMMIT}"
  git -C "${CACHE_ROOT}/source" checkout --detach "${VOXCPM_COMMIT}"
  git -C "${CACHE_ROOT}/source" reset --hard "${VOXCPM_COMMIT}"
fi
git -C "${CACHE_ROOT}/source" apply "${PROJECT_ROOT}/tools/board/patches/voxcpm-server-inference-timesteps.patch"

model_path="${CACHE_ROOT}/models/${MODEL_NAME}"
if [[ -n ${VOXCPM_MODEL_SOURCE:-} ]]; then
  cp --reflink=auto -- "${VOXCPM_MODEL_SOURCE}" "${model_path}"
elif [[ ! -f ${model_path} ]]; then
  curl --fail --location --retry 12 --retry-all-errors --continue-at - "${MODEL_URL}" --output "${model_path}"
fi
printf '%s  %s\n' "${MODEL_SHA256}" "${model_path}" | sha256sum --check

cmake -S "${CACHE_ROOT}/source" -B "${CACHE_ROOT}/build" \
  -DCMAKE_BUILD_TYPE=Release \
  -DVOXCPM_CUDA=OFF \
  -DVOXCPM_VULKAN=OFF \
  -DVOXCPM_NATIVE=ON \
  -DVOXCPM_BUILD_TESTS=OFF \
  -DVOXCPM_BUILD_BENCHMARK=OFF \
  -DVOXCPM_BUILD_EXAMPLES=ON \
  -DVOXCPM_ENABLE_OPUS=OFF
cmake --build "${CACHE_ROOT}/build" --target voxcpm-server --parallel "$(nproc)"

sudo install -d -m 755 "${INSTALL_ROOT}/bin" "${INSTALL_ROOT}/models"
sudo install -d -o wenkang -g wenkang -m 750 /var/lib/visual-companion-voxcpm/voices
sudo install -m 755 "${CACHE_ROOT}/build/examples/voxcpm-server" "${INSTALL_ROOT}/bin/voxcpm-server"
sudo install -m 644 "${model_path}" "${INSTALL_ROOT}/models/${MODEL_NAME}"
sudo systemctl disable --now visual-companion-voxcpm.service 2>/dev/null || true
sudo rm -f /etc/systemd/system/visual-companion-voxcpm.service
sudo systemctl daemon-reload
printf 'VoxCPM.cpp 已安装；控制网关会按请求启动并在合成后释放模型。\n'
