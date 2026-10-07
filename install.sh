#!/bin/bash
# One-command installer for the cp2k-forge Python environment. Safe on a login node:
# no sudo, no module assumptions, idempotent (reuses an existing venv). It installs only
# the Python side; DFT labelling additionally needs a CP2K binary (checked by --check).
#
# Usage (from this directory):
#   ./install.sh                 # CPU / whatever torch pip resolves by default
#   ./install.sh --cpu           # force the CPU-only torch wheel
#   ./install.sh --cuda cu124    # install a CUDA 12.4 torch wheel first (GPU nodes)
#   ./install.sh --gpu           # probe nvidia-smi and print the matching --cuda hint
#   PYTHON=python3.11 ./install.sh --venv .venv --cuda cu121
#
# The CUDA build is deliberately explicit, never guessed: a mismatched torch/CUDA wheel is
# the most common GPU install failure. Pick the tag matching your driver from
# https://pytorch.org/get-started/locally/ (e.g. cu118, cu121, cu124).
set -euo pipefail
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"
VENV="venv"
CUDA=""
FORCE_CPU=0
GPU_PROBE=0

while [ $# -gt 0 ]; do
  case "$1" in
    --cuda)  CUDA="${2:?--cuda needs a wheel tag, e.g. cu124}"; shift 2 ;;
    --cpu)   FORCE_CPU=1; shift ;;
    --gpu)   GPU_PROBE=1; shift ;;
    --venv)  VENV="$2"; shift 2 ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

if [ "$GPU_PROBE" = "1" ]; then
  if command -v nvidia-smi >/dev/null 2>&1; then
    echo "== nvidia-smi detected:"
    nvidia-smi --query-gpu=name,driver_version --format=csv,noheader 2>/dev/null || true
    echo "== re-run with the CUDA tag matching your driver, e.g. ./install.sh --cuda cu124"
    echo "   (tags: https://pytorch.org/get-started/locally/)"
  else
    echo "== no nvidia-smi found; this looks like a CPU node. Use ./install.sh (or --cpu)."
  fi
  exit 0
fi

echo "== creating/using virtualenv: $VENV"
[ -d "$VENV" ] || "$PYTHON" -m venv "$VENV"
# Call the venv interpreter directly rather than sourcing 'activate' — sourcing activate
# under `set -u` is an unbound-variable footgun and mutates PATH for no benefit here.
PYBIN="$VENV/bin/python"
"$PYBIN" -m pip install -U pip wheel

echo "== installing cp2k-forge (editable) with the train + plot extras"
"$PYBIN" -m pip install -e ".[train,plot]"

# Install the chosen torch wheel LAST, so an explicit CPU/CUDA build is not clobbered by the
# requirements resolution above (which would otherwise pull the default-index wheel). Nothing
# specified -> keep whatever the requirements pulled (CPU on macOS, CUDA on Linux by default).
TORCH_IDX=""
if [ -n "${TORCH_INDEX_URL:-}" ]; then
  TORCH_IDX="$TORCH_INDEX_URL"
elif [ -n "$CUDA" ]; then
  TORCH_IDX="https://download.pytorch.org/whl/$CUDA"
elif [ "$FORCE_CPU" = "1" ]; then
  TORCH_IDX="https://download.pytorch.org/whl/cpu"
fi
if [ -n "$TORCH_IDX" ]; then
  echo "== installing torch from $TORCH_IDX (explicit build, applied last)"
  "$PYBIN" -m pip install --force-reinstall --no-deps torch --index-url "$TORCH_IDX"
fi

echo
echo "== done. torch: $("$PYBIN" -c 'import torch; print(torch.__version__)' 2>/dev/null || echo 'not importable')"
echo "== next steps:"
echo "   . $VENV/bin/activate"
echo "   cp2k-forge --check                        # verify the environment"
echo "   cp2k-forge --config configs/smoke.yaml    # ~2 min self-test, no CP2K needed"
