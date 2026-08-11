#!/usr/bin/env bash
# Cross-platform Python launcher for AI log hooks.
# Avoids the non-functional Microsoft Store python/python3 aliases on Windows.
set -u

run_if_valid() {
  local executable="$1"
  shift
  if "$executable" "$@" -c "import sys" >/dev/null 2>&1; then
    exec "$executable" "$@" "${PYRUN_ARGS[@]}"
  fi
}

PYRUN_ARGS=("$@")

# Prefer the repository virtual environment so hooks use project dependencies.
if [ -x ".venv/Scripts/python.exe" ]; then
  exec ".venv/Scripts/python.exe" "${PYRUN_ARGS[@]}"
fi
if [ -x ".venv/bin/python" ]; then
  exec ".venv/bin/python" "${PYRUN_ARGS[@]}"
fi

# On Windows, the py launcher resolves installed Python versions reliably.
if command -v py >/dev/null 2>&1; then
  run_if_valid py -3
fi

# Only use PATH candidates after proving they can actually start Python.
if command -v python3 >/dev/null 2>&1; then
  run_if_valid python3
fi
if command -v python >/dev/null 2>&1; then
  run_if_valid python
fi

# Last-resort probe for common Git Bash paths.
shopt -s nullglob 2>/dev/null || true
for candidate in \
  /c/Users/*/AppData/Local/Programs/Python/Python*/python.exe \
  "/c/Program Files/Python"*/python.exe \
  "/c/Program Files (x86)/Python"*/python.exe \
  /c/Python*/python.exe; do
  if [ -x "$candidate" ]; then
    exec "$candidate" "${PYRUN_ARGS[@]}"
  fi
done

echo "[ai-log] Python runtime not found; logs were not processed." >&2
exit 1
