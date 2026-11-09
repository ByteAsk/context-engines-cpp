# context-engines-cpp

Code for **Beyond Text Search: Context Engines for C++** (Pratyush Saini, CTO, ByteAsk Research,
pratyush@byteask.ai; Anirudha Kulkarni, CEO, ByteAsk Research, anirudha@byteask.ai;
Aman Gupta, Carnegie Mellon University, amangupt@alumni.cmu.edu; November 2026).

Coding agents have to find the code an issue needs changed before they can fix it, and in C and C++ that depends on
the build: which overload a call reaches, which template is instantiated and which `#if` branch is compiled. ByteAsk
Context understands a codebase the way the project's own build does. The paper compares it with three code search
tools, sgrep, Probe and Graphify, each given the input its own documentation asks for, on real issues from open-source
C and C++ projects. Two tools are compared only on the issues both have fully indexed. How often a file that needed
changing came first:

<!-- headline table -->
| Compared with | Issues | ByteAsk Context | Tool | Difference |
|---|---|---|---|---|
| sgrep | 30 | 57% | 30% | +27 points |
| Probe | 30 | 57% | 20% | +37 points |
| Graphify | 35 | 83% | 26% | +57 points |
<!-- /headline table -->

Probe is shown with its better input (an agent-written query); Graphify ran its documented code-only build.

Paper: [byteask.ai/research/context-engines-cpp](https://byteask.ai/research/context-engines-cpp). The PDF is in this
repository: `paper.pdf`.

## Tasks

`tasks.tsv` lists 12 public tasks, real issues from 8 repositories: HDF5, SPIRV-Tools, PROJ, Arrow,
Highway, QuantLib, OpenTelemetry C++ and OpenCV. Each row gives the task name, the repository, its base commit, the
issue and the pull request that fixed it. Every task is in the [Harbor](https://github.com/laude-institute/harbor)
task format:

- `instruction.md`: the issue text, and the answer to give: the files to change, most likely first, in
  `/app/answer.txt`;
- `environment/`: the repository at its base commit as a single commit (no later commits), the three open-source
  tools at the paper's versions, git, CMake and compilers, and each tool's input from the paper (`/opt/task/`);
- `tests/`: the verifier, with the files the fix changed. The reward is 1 when the first file of the answer is one of
  them, and 0 otherwise;
- `solution/`: the reference answer.

```bash
./get_tasks.sh                              # all 12 tasks from the tasks-v1 release (690 MB)
./get_tasks.sh lballabio__QuantLib-2792     # or some of them
```

## Run it

You need Linux with Docker (compose v2 and buildx), 4 CPU cores and 16 GB of memory per trial, and Harbor 0.25.0
(`uv tool install harbor==0.25.0`). Each arm is one tool, set up as its own documentation says and given the input
the paper gave it:

| Arm | Tool | Input |
|---|---|---|
| `context` | ByteAsk Context, through its MCP server | the issue text, verbatim |
| `sgrep` | sgrep 0.3.0 (`sgrep QUERY -n N --json`; it indexes the repository on first use) | 1 to 3 plain-English queries |
| `probe-keyword` | Probe 0.6.0-rc345 as an MCP server (`probe mcp --timeout 300`, tool `search_code`) | a keyword query built from the issue's identifiers |
| `probe-agent` | the same | 1 to 3 queries in Probe's search syntax |
| `graphify` | Graphify 0.9.103 (`graphify extract . --code-only`, `graphify cluster-only .`, then `graphify query`) | 1 to 3 plain-language questions |

The written inputs were written by Claude Opus 5.5 from the issue, the repository name and the tool's own
description, with one prompt template for every tool; they ship in each task, so a run needs no model.

```bash
./run.sh sgrep lballabio__QuantLib-2792
./run.sh probe-agent lballabio__QuantLib-2792
./run.sh graphify lballabio__QuantLib-2792
```

**ByteAsk Context.** Set it up as [byteask.ai/context](https://byteask.ai/context) describes, and sign in once. The arm
needs the access token of that sign-in in `BYTEASK_CONTEXT_TOKEN`: after you authenticate the `byteask` MCP server in
Claude Code (`/mcp`), it is in `~/.claude/.credentials.json`, under `mcpOAuth`.

```bash
export BYTEASK_CONTEXT_TOKEN=...
./run.sh context lballabio__QuantLib-2792
```

In the trial's container the arm gives the repository the two things ByteAsk Context needs, an `origin` remote and a
`compile_commands.json` from the project's own CMake configure, indexes it with ByteAsk Context (the files the build
reads are uploaded to ByteAsk, as the setup page explains), and then asks `find_code_for_task` with the issue text
exactly as written.

**Check a task.** `./run.sh oracle TASK` writes the reference answer (reward 1); `./run.sh nop TASK` writes nothing
(reward 0). Each trial's result, the tool's raw answers (`agent/calls.json`) and the verifier's output are in `jobs/`; `python3 score.py` then shows 100% for `oracle` and 0% for `nop`.

## The sample

Run every arm on the 12 public tasks in `tasks.tsv`, then score what you ran. The open-source arms need no key; the
`context` arm needs `BYTEASK_CONTEXT_TOKEN` (above). Trials run one at a time.

```bash
./get_tasks.sh
for arm in context sgrep probe-keyword probe-agent graphify; do
  for task in $(awk -F'\t' 'NR > 1 {print $1}' tasks.tsv); do ./run.sh "$arm" "$task"; done
done
python3 score.py
```

A smaller sample works the same way: pick a few task names from `tasks.tsv` for the inner loop. You can run an arm
more than once on a task; `score.py` takes the mean of its trials on each issue.

`score.py` reads every trial in `jobs/` (or the folder you give it) and prints, per arm, the trials, the issues and
the share of issues where a file the fix changed came first. It then compares ByteAsk Context with each other arm on
the issues both ran. It needs only Python 3.

## What to expect

On its full issue sets the paper finds that a needed file came first for ByteAsk Context on 57% of issues, against 30%
for sgrep and 20% for Probe (30 issues), and on 83% against 26% for Graphify (35 issues). Twelve tasks are a small
sample, so your numbers will differ from these, and a single issue moves a share by about 8 points.

## Layout

```
tasks.tsv          the 12 public Harbor tasks: name, repository, base commit, issue, fix
get_tasks.sh       download tasks from the tasks-v1 release into tasks/ and check them
run.sh             one trial through Harbor: ./run.sh ARM TASK [JOBS_DIR]
agent.py           the Harbor agents of the five arms
score.py           score every trial in jobs/ and print the per-arm summary
paper.pdf          the paper
```

## Citation

```bibtex
@misc{saini2026contextengines,
  title        = {Beyond Text Search: Context Engines for C++},
  author       = {Saini, Pratyush and Kulkarni, Anirudha and Gupta, Aman},
  year         = {2026},
  month        = nov,
  institution  = {ByteAsk Research},
  howpublished = {\url{https://byteask.ai/research/context-engines-cpp}},
  note         = {Preprint. Code and tasks: \url{https://github.com/ByteAsk/context-engines-cpp}}
}
```

## License

The scripts are MIT licensed (`LICENSE`). Each repository snapshot in the tasks keeps its project's own license, and each issue text belongs to its project.
