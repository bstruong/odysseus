#!/usr/bin/env bash
# =============================================================================
# scripts/serve-rx7600.sh
# 
# Principal Architecture: 100% VRAM General AI Server for AMD Radeon RX 7600 (8GB)
# Host Target: Intel Haswell Core i7-4790K (4c/8t) + DDR3 RAM + CachyOS / Linux
#
# ZERO SPILLOVER MANDATE:
#   DDR3 bandwidth (~20 GB/s) severely throttles decode. All weights, attention,
#   and KV context MUST fit 100% inside the 8GB GDDR6 VRAM (-ngl 99).
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STACK_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
CONFIG_DIR="${STACK_DIR}/config"
MODELS_INI="${STACK_DIR}/models.ini"

# Server Networking
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8080}"

# Hardware Engine Detection
# Default to llama-server from PATH or local builds
LLAMA_SERVER_BIN="${LLAMA_SERVER_BIN:-$(command -v llama-server || true)}"
if [[ -z "${LLAMA_SERVER_BIN}" ]]; then
    # Check known local build locations
    for candidate in \
        "/usr/local/bin/llama-server" \
        "/usr/bin/llama-server" \
        "${HOME}/Projects/berserker/experiments/llama.cpp-qwen4exp/build/bin/llama-server" \
        "${STACK_DIR}/bin/llama-server"; do
        if [[ -x "${candidate}" ]]; then
            LLAMA_SERVER_BIN="${candidate}"
            break
        fi
    done
fi

if [[ -z "${LLAMA_SERVER_BIN}" || ! -x "${LLAMA_SERVER_BIN}" ]]; then
    echo "ERROR: llama-server executable not found. Please install llama.cpp with Vulkan/ROCm backend." >&2
    exit 1
fi

# -----------------------------------------------------------------------------
# GPU Backend Environment Configuration
# -----------------------------------------------------------------------------
# For ROCm on Navi 33 (RX 7600 gfx1102), override GFX version if using ROCm
export HSA_OVERRIDE_GFX_VERSION="${HSA_OVERRIDE_GFX_VERSION:-11.0.0}"

# For Vulkan backend (Recommended for CachyOS / Mesa RADV):
export GGML_VULKAN_DEVICE="${GGML_VULKAN_DEVICE:-0}"

# -----------------------------------------------------------------------------
# Haswell CPU Hardware Alignment
# Physical cores minus 1 = 3 threads on a 4-core Haswell CPU.
# Leaves 1 physical core for OS scheduling, driver interrupt handling, and I/O.
# -----------------------------------------------------------------------------
PHYSICAL_CORES=$(lscpu -p | grep -E -v '^#' | sort -u -t, -k 2,2 | wc -l || echo 4)
RECOMMENDED_THREADS=$(( PHYSICAL_CORES > 1 ? PHYSICAL_CORES - 1 : 1 ))
THREADS="${THREADS:-${RECOMMENDED_THREADS}}"

# -----------------------------------------------------------------------------
# Execution Parameters (100% VRAM Envelope)
# -----------------------------------------------------------------------------
# -ngl 99          : Force all layers into GPU VRAM (zero CPU layer offload)
# --no-mmap        : Pre-load weights completely into RAM/VRAM; prevent disk paging
# --mlock          : Memory lock allocations to prevent OS swapping
# --ubatch 1024    : Micro-batch scaling for 800-1,100+ tok/s prompt prefill
# --batch-size 2048: Physical prompt processing batch
# --cache-reuse 256: 256-token context chunk cache reuse (prompt delta caching)
# KV Cache:
#   turbo4 / turbo2 or q4_0 / q2_k to compress KV into ~1.0-1.5 GB VRAM budget.
# -----------------------------------------------------------------------------
PRESET="${1:-gemma4-qat-12b}"

echo "=============================================================================="
echo " Starting 100% VRAM llama-server on AMD Radeon RX 7600 (8GB VRAM)"
echo " Host CPU: Haswell (${PHYSICAL_CORES} physical cores) -> Threads allocated: ${THREADS}"
echo " Preset:   ${PRESET} (via ${MODELS_INI})"
echo " Endpoint: http://${HOST}:${PORT}/v1"
echo "=============================================================================="

# Launch mode: If models.ini exists, use router / preset loading
if [[ -f "${MODELS_INI}" ]]; then
    exec "${LLAMA_SERVER_BIN}" \
        --host "${HOST}" \
        --port "${PORT}" \
        --models-preset "${MODELS_INI}" \
        --models-max 1 \
        --threads "${THREADS}" \
        --threads-batch "${THREADS}" \
        --n-gpu-layers 99 \
        --flash-attn on \
        --no-mmap \
        --mlock \
        --batch-size 2048 \
        --ubatch-size 1024 \
        --cache-type-k q4_0 \
        --cache-type-v q2_k \
        --cache-prompt \
        --cache-reuse 256 \
        --parallel 1 \
        --jinja \
        --metrics \
        --slots
else
    echo "Notice: ${MODELS_INI} not found, launching with direct CLI flags..."
    exec "${LLAMA_SERVER_BIN}" \
        --host "${HOST}" \
        --port "${PORT}" \
        --threads "${THREADS}" \
        --threads-batch "${THREADS}" \
        --n-gpu-layers 99 \
        --flash-attn on \
        --no-mmap \
        --mlock \
        --batch-size 2048 \
        --ubatch-size 1024 \
        --cache-type-k q4_0 \
        --cache-type-v q2_k \
        --cache-prompt \
        --cache-reuse 256 \
        --parallel 1
fi
