#!/usr/bin/env bash
# run.sh ARM TASK [JOBS_DIR]: one trial of one tool on one task, through Harbor 0.25.0.
#   ARM   context | sgrep | probe-keyword | probe-agent | graphify | oracle | nop
#   TASK  a task name from tasks.tsv, fetched with ./get_tasks.sh
# context   ByteAsk Context through its MCP server. Needs BYTEASK_CONTEXT_TOKEN (see the README).
# sgrep, probe-keyword, probe-agent, graphify: the open-source tools in the task's image, no key needed.
# oracle writes the reference answer (reward 1); nop writes nothing (reward 0).
# The verifier scores the first file of /app/answer.txt: 1 if the issue's fix changed it, else 0.
set -euo pipefail
arm=$1 task=$2 jobs=${3:-jobs}
here=$(cd "$(dirname "$0")" && pwd)
dir="$here/tasks/$task"
[ -d "$dir" ] || { echo "no $dir: run ./get_tasks.sh $task first" >&2; exit 1; }
export HARBOR_TELEMETRY=0 PYTHONPATH="$here${PYTHONPATH:+:$PYTHONPATH}"
case "$arm" in
  context) : "${BYTEASK_CONTEXT_TOKEN:?set BYTEASK_CONTEXT_TOKEN}"; agent=(-a agent:ByteAskContext);;
  sgrep) agent=(-a agent:Sgrep);;
  probe-keyword) agent=(-a agent:ProbeKeyword);;
  probe-agent) agent=(-a agent:ProbeAgent);;
  graphify) agent=(-a agent:Graphify);;
  oracle|nop) agent=(-a "$arm");;
  *) echo "unknown arm $arm" >&2; exit 2;;
esac
exec harbor run -q -y -p "$dir" "${agent[@]}" -n 1 -o "$jobs" --job-name "$arm-$task-$(date +%Y%m%d-%H%M%S)"
