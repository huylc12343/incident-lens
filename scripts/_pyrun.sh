#!/usr/bin/env bash
# Cross-platform Python launcher for AI log hooks.
# Tries a working project/PATH Python first; on Windows, falls back to common
# install locations before trying the Python launcher. Every candidate is
# executed once so a stale Windows Store alias or broken virtualenv is skipped.
# Designed to be sourced or called as: bash scripts/_pyrun.sh <script> [args...]
#
# Exits 0 silently if no Python is found — hooks must never block the AI tool.
set -u

PY_CMD=()

python_works() {
  "$@" -c 'import sys; raise SystemExit(sys.version_info < (3, 10))' \
    >/dev/null 2>&1
}

for cand in .venv/Scripts/python.exe .venv/bin/python; do
  if [ -x "$cand" ] && python_works "$cand"; then
    PY_CMD=("$cand")
    break
  fi
done

if [ ${#PY_CMD[@]} -eq 0 ] && command -v python3 >/dev/null 2>&1 \
    && python_works python3; then
  PY_CMD=(python3)
elif [ ${#PY_CMD[@]} -eq 0 ] && command -v python >/dev/null 2>&1 \
    && python_works python; then
  PY_CMD=(python)
fi

if [ ${#PY_CMD[@]} -eq 0 ]; then
  # Git hooks can receive a stripped PATH, so probe standard Windows installs.
  shopt -s nullglob 2>/dev/null || true
  for cand in \
    /c/Users/*/AppData/Local/Programs/Python/Python*/python.exe \
    "/c/Program Files/Python"*/python.exe \
    "/c/Program Files (x86)/Python"*/python.exe \
    /c/Python*/python.exe; do
    if [ -x "$cand" ] && python_works "$cand"; then
      PY_CMD=("$cand")
      break
    fi
  done
  shopt -u nullglob 2>/dev/null || true
fi

if [ ${#PY_CMD[@]} -eq 0 ] && command -v py >/dev/null 2>&1 \
    && python_works py -3; then
  PY_CMD=(py -3)
fi

[ ${#PY_CMD[@]} -gt 0 ] || exit 0
exec "${PY_CMD[@]}" "$@"
