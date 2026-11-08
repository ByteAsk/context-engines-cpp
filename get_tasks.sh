#!/usr/bin/env bash
# get_tasks.sh [TASK...]: download tasks from the repository's tasks-v1 release into tasks/ (all of tasks.tsv by default)
# and check them against SHA256SUMS. Each archive is one Harbor task folder: instruction.md, environment/ (the
# repository at its base commit as app.tar, and the tools), tests/ (the verifier and the reference files) and solution/.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
base=${TASKS_URL:-https://github.com/ByteAsk/context-engines-cpp/releases/download/tasks-v1}
mkdir -p "$here/tasks" "$here/.cache"
[ -f "$here/.cache/SHA256SUMS" ] || curl -fsSL "$base/SHA256SUMS" -o "$here/.cache/SHA256SUMS"
tasks=("$@"); [ ${#tasks[@]} -gt 0 ] || mapfile -t tasks < <(awk -F'\t' 'NR > 1 {print $1}' "$here/tasks.tsv")
for t in "${tasks[@]}"; do
  f="$here/.cache/$t.tar.gz"
  [ -f "$f" ] || curl -fL --retry 3 "$base/$t.tar.gz" -o "$f"
  (cd "$here/.cache" && grep " $t.tar.gz\$" SHA256SUMS | sha256sum -c --quiet -) || { echo "checksum mismatch: $t" >&2; exit 1; }
  rm -rf "$here/tasks/$t" && tar -xzf "$f" -C "$here/tasks"
  echo "$t: ready"
done
