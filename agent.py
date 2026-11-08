"""Harbor agents for the arms of context-engines-cpp: one per tool, each set up as its own public documentation says and
given the input the paper gave it (the task's /opt/task/inputs.json). Each arm writes the files its tool returned, in
order and without duplicates, to /app/answer.txt (the task's verifier scores the first one), and keeps the tool's raw
answers in the trial's agent log.

  ByteAskContext  ByteAsk Context as https://byteask.ai/context describes it: the repository gets a git `origin` remote
                  and a compile_commands.json from the project's own CMake configure; the arm indexes it through the
                  ByteAsk MCP server (index_repository, then its collect script: preview, upload), waits until the
                  index is ready, and calls find_code_for_task with the issue text exactly as written. Needs
                  BYTEASK_CONTEXT_TOKEN (see the README).
  Sgrep           sgrep 0.3.0: `sgrep QUERY -n N --json` with each plain-English query; it indexes /app on first use.
  ProbeKeyword    Probe 0.6.0-rc345 as an MCP server (`probe mcp --timeout 300`), tool search_code, keyword query.
  ProbeAgent      the same, with the agent-written query.
  Graphify        Graphify 0.9.103: `graphify extract . --code-only`, `graphify cluster-only .`, then
                  `graphify query QUESTION` for each question (graph-size cap raised).

Use with: PYTHONPATH=. harbor run -p tasks/TASK -a agent:Sgrep ... (see run.sh)."""
import json
import os
import re
import shlex
from pathlib import Path

from harbor.agents.base import BaseAgent
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext

LOG = "/logs/agent"
CAP = 600          # seconds per tool call, as in the paper
CONTEXT_MCP = os.environ.get("BYTEASK_CONTEXT_URL", "https://context.byteask.ai/mcp")


def strip_app(p):
    return re.sub(r"^(\./|/app/|app/)", "", p.strip())


def parse_sgrep(out):
    hits = json.loads(out)
    if not isinstance(hits, list):
        raise ValueError("not a list of hits")
    return [strip_app(h.get("path", "")) for h in hits]


def parse_probe(out):
    lines = out.splitlines()
    if not lines or not lines[0].startswith("Pattern:"):
        raise ValueError("not a Probe search result")
    m = re.search(r"<matches>(.*?)(?:</matches>|<skipped_files>|\Z)", out, re.S)
    if m:
        return [strip_app(f.group(1)) for f in re.finditer(r'<file path="([^"]+)">', m.group(1))]
    if "No results found." in out:
        return []
    raise ValueError("neither file blocks nor Probe's empty result")


def parse_graphify(out):
    if not re.match(r"Graph: .*\| (\d+) nodes found", out):
        raise ValueError("not a Graphify query result")
    return [strip_app(x.group(2)) for x in re.finditer(r"NODE\s+(.+?)\s+\[src=([^\s\]]+)(?:\s+loc=L(\d+))?", out)]


def parse_context(out):
    files = [m.group(3) for m in re.finditer(r"(?m)^\s*(\d+)\.\s+(\S.*?)\s+—\s+([^\s:]+):(\d+)", out)]
    if not files:
        raise ValueError("no ranked places in the answer")
    return [strip_app(f) for f in files]


class _Arm(BaseAgent):
    KEY = ""          # the arm's key in inputs.json

    def __init__(self, logs_dir, model_name=None, **kwargs):
        super().__init__(logs_dir=logs_dir, model_name=model_name, **kwargs)

    def version(self) -> str:
        return "1.0.0"

    async def _sh(self, env, cmd, timeout=CAP, envs=None):
        r = await env.exec(command=cmd, timeout_sec=timeout, env=envs)
        return r.return_code, (r.stdout or ""), (r.stderr or "")

    async def _tool(self, env, cmd, timeout=CAP, envs=None):
        """one tool call: its stdout and stderr kept apart (the container's exec merges them otherwise)"""
        rc, _, _ = await self._sh(env, f"({cmd}) > /tmp/ce-out 2> /tmp/ce-err", timeout=timeout, envs=envs)
        _, out, _ = await self._sh(env, "cat /tmp/ce-out", timeout=120)
        _, err, _ = await self._sh(env, "tail -c 4000 /tmp/ce-err", timeout=120)
        return rc, out, err

    async def _inputs(self, env):
        rc, out, _ = await self._sh(env, "cat /opt/task/inputs.json")
        return json.loads(out)[self.KEY]

    async def _answer(self, env, files, raw):
        seen = []
        for f in files:
            if f and f not in seen:
                seen.append(f)
        Path(self.logs_dir).mkdir(parents=True, exist_ok=True)
        (Path(self.logs_dir) / "calls.json").write_text(json.dumps(raw, indent=1))
        body = "\n".join(seen) + ("\n" if seen else "")
        await self._sh(env, f"mkdir -p {LOG} && printf %s {shlex.quote(body)} > /app/answer.txt")

    async def setup(self, environment: BaseEnvironment) -> None:
        pass


class Sgrep(_Arm):
    KEY = "sgrep"

    @staticmethod
    def name() -> str:
        return "sgrep"

    async def run(self, instruction, environment, context):
        raw, files = [], []
        # sgrep keeps its index in its cache folder; the first search builds it (and downloads its embedding model)
        await self._sh(environment, "mkdir -p /tmp/sgrep-cache", timeout=60)
        env = {"SGREP_CACHE_DIR": "/tmp/sgrep-cache", "SGREP_CACHE_MAX_BYTES": "68719476736"}
        await self._sh(environment, "cd /app && sgrep 'parse command line options and print usage' -n 5 > /dev/null",
                       timeout=3600, envs=env)
        for a in await self._inputs(environment):
            n = f" -n {int(a['n'])}" if a.get("n") else ""
            rc, out, err = await self._tool(environment, f"cd /app && sgrep {shlex.quote(a['query'])}{n} --json", envs=env)
            raw.append({"args": a, "rc": rc, "out": out, "err": err[-2000:]})
            try:
                files += parse_sgrep(out) if rc == 0 else []
            except ValueError:
                pass
        await self._answer(environment, files, raw)


class _Probe(_Arm):
    async def run(self, instruction, environment, context):
        raw, files = [], []
        for a in await self._inputs(environment):
            cmd = ("cd /app && node /opt/ce/mcp_call.mjs --stdio 'probe mcp --timeout 300' search_code "
                   f"{shlex.quote(json.dumps(a))}")
            rc, out, err = await self._tool(environment, cmd)
            raw.append({"args": a, "rc": rc, "out": out, "err": err[-2000:]})
            try:
                files += parse_probe(out)
            except ValueError:
                pass
        await self._answer(environment, files, raw)


class ProbeKeyword(_Probe):
    KEY = "probe-keyword"

    @staticmethod
    def name() -> str:
        return "probe-keyword"


class ProbeAgent(_Probe):
    KEY = "probe-agent"

    @staticmethod
    def name() -> str:
        return "probe-agent"


class Graphify(_Arm):
    KEY = "graphify"

    @staticmethod
    def name() -> str:
        return "graphify"

    async def run(self, instruction, environment, context):
        raw, files = [], []
        # the documented offline build, code only, in a copy of the tree (it writes graphify-out/ next to the code)
        rc, out, err = await self._sh(environment, "rm -rf /tmp/gview && cp -a /app /tmp/gview && cd /tmp/gview && "
                                      "graphify extract . --code-only && graphify cluster-only .", timeout=3600)
        raw.append({"build": rc, "err": err[-2000:]})
        genv = {"GRAPHIFY_OUT": "/tmp/gout", "GRAPHIFY_MAX_GRAPH_BYTES": "2GB"}
        for a in await self._inputs(environment):
            opt = (f" --depth {int(a['depth'])}" if a.get("depth") else "") + (f" --budget {int(a['budget'])}" if a.get("budget") else "")
            rc, out, err = await self._tool(environment, f"cd /tmp/gview && graphify query {shlex.quote(a['question'])} "
                                          f"--graph /tmp/gview/graphify-out/graph.json{opt}", envs=genv)
            raw.append({"args": a, "rc": rc, "out": out, "err": err[-2000:]})
            try:
                files += parse_graphify(out) if rc == 0 else []
            except ValueError:
                pass
        await self._answer(environment, files, raw)


MCP_CLIENT = r'''
import json, os, sys, urllib.request
url, token = os.environ["CTX_URL"], os.environ["CTX_TOKEN"]
hdr = {"Authorization": "Bearer " + token, "content-type": "application/json", "accept": "application/json, text/event-stream"}
sid, i = None, 0
def rpc(method, params, notify=False):
    global sid, i
    i += 1
    msg = {"jsonrpc": "2.0", "method": method, "params": params, **({} if notify else {"id": i})}
    h = dict(hdr, **({"mcp-session-id": sid} if sid else {}))
    r = urllib.request.urlopen(urllib.request.Request(url, json.dumps(msg).encode(), h), timeout=900)
    txt = r.read().decode()
    sid = r.headers.get("mcp-session-id") or sid
    if (r.headers.get("content-type") or "").startswith("text/event-stream"):
        txt = "\n".join(l[5:] for l in txt.splitlines() if l.startswith("data:"))
    return json.loads(txt) if txt.strip() else {}
rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "context-engines-cpp", "version": "1"}})
rpc("notifications/initialized", {}, notify=True)
r = rpc("tools/call", {"name": sys.argv[1], "arguments": json.loads(sys.argv[2])})
res = r.get("result") or {}
print("\n".join(c.get("text", "") for c in res.get("content", [])))
sys.exit(1 if ("error" in r or res.get("isError")) else 0)
'''


class ByteAskContext(_Arm):
    """ByteAsk Context over its MCP server (https://context.byteask.ai/mcp), set up as https://byteask.ai/context says:
    a git origin remote and a compile_commands.json, index once (index_repository and its steps, the user having allowed
    indexing), then find_code_for_task with the task text exactly as written."""
    KEY = "context"

    @staticmethod
    def name() -> str:
        return "byteask-context"

    async def setup(self, environment: BaseEnvironment) -> None:
        if not os.environ.get("BYTEASK_CONTEXT_TOKEN"):
            raise RuntimeError("set BYTEASK_CONTEXT_TOKEN (see the README)")
        await environment.upload_file(source_path=self._client_file(), target_path="/opt/ce/ctx_mcp.py")

    def _client_file(self):
        p = Path(self.logs_dir) / "ctx_mcp.py"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(MCP_CLIENT)
        return p

    async def _mcp(self, env, tool, args, timeout=900):
        e = {"CTX_URL": CONTEXT_MCP, "CTX_TOKEN": os.environ["BYTEASK_CONTEXT_TOKEN"]}
        return await self._tool(env, f"python3 /opt/ce/ctx_mcp.py {tool} {shlex.quote(json.dumps(args))}", timeout=timeout, envs=e)

    async def run(self, instruction, environment, context):
        raw = []
        _, tj, _ = await self._sh(environment, "cat /opt/task/task.json")
        task = json.loads(tj)
        # 1. prerequisites (byteask.ai/context): a git origin remote and a compile_commands.json from the project's own
        #    CMake configure (configure only, no build), in build/byteask
        src = "/app" if task["cmake_source"] == "." else f"/app/{task['cmake_source']}"
        prep = (f"cd /app && (git remote get-url origin >/dev/null 2>&1 || git remote add origin {shlex.quote(task['url'])}) && "
                f"cmake -S {src} -B /app/build/byteask -DCMAKE_EXPORT_COMPILE_COMMANDS=ON "
                + " ".join(shlex.quote(a) for a in task["cmake_args"]) + f" > {LOG}/configure.log 2>&1")
        rc, _, _ = await self._sh(environment, f"mkdir -p {LOG} && " + prep, timeout=1800)
        raw.append({"configure": rc})
        # 2. index (index_repository returns the steps: fetch and check the collect script, preview, upload with a key)
        rc, out, err = await self._mcp(environment, "index_repository", {"repo_url": task["url"], "workdir": "/app"})
        raw.append({"index_repository": rc, "out": out, "err": err[-2000:]})
        fetch = next((l.strip() for l in out.splitlines() if l.strip().startswith("mkdir -p ~/.cache/byteask-context")), None)
        key = re.search(r"BYTEASK_KEY=(\S+)", out)
        if fetch and key:
            k = {"BYTEASK_KEY": key.group(1)}
            script = "~/.cache/byteask-context/collect.py"
            rc1, o1, e1 = await self._sh(environment, f"cd /app && {fetch.split(' && echo')[0]}", timeout=300)
            rc2, o2, e2 = await self._tool(environment, f"cd /app && python3 {script} preview --compdb /app/build/byteask "
                                         "--json", timeout=1800)
            try:
                pid = json.loads(o2).get("preview_id")
            except ValueError:
                pid = None
            raw.append({"collect": [rc1, rc2], "preview": o2[-4000:], "err": (e1 + e2)[-2000:]})
            if pid:
                rc3, o3, e3 = await self._sh(environment, f"cd /app && python3 {script} upload --preview {shlex.quote(pid)}",
                                             timeout=3600, envs=k)
                raw.append({"upload": rc3, "out": o3[-2000:], "err": e3[-2000:]})
                # 3. wait until the index is ready (`status` waits for ready or failed), up to 45 minutes
                rc4, o4, _ = await self._sh(environment, f"cd /app && python3 {script} status", timeout=2700, envs=k)
                raw.append({"status": rc4, "out": o4[-2000:]})
        # 4. the task, exactly as written
        files = []
        for a in await self._inputs(environment):
            rc, out, err = await self._mcp(environment, "find_code_for_task", dict(a, workdir="/app", repo_url=task["url"]))
            raw.append({"args": {"task": a.get("task", "")[:200]}, "rc": rc, "out": out, "err": err[-2000:]})
            try:
                files += parse_context(out) if rc == 0 else []
            except ValueError:
                pass
        await self._answer(environment, files, raw)
