#!/usr/bin/env python3
"""score.py [JOBS_DIR]: score every trial in JOBS_DIR (default jobs/), as written by ./run.sh, and print per arm the
number of trials and the paper's metric: the share of issues where a file the fix changed came first. A trial's
reward is the task verifier's (verifier/reward.txt: 1 when the first file of /app/answer.txt is one the fix changed,
else 0); a trial without a reward (it failed before the verifier ran) counts as 0. An arm's value on an issue is the
mean over its trials of that issue. ByteAsk Context is then compared with each other arm on the issues both ran.
Python 3.8 or newer, standard library only."""
import collections, glob, json, os, re, sys

JOBS = sys.argv[1] if len(sys.argv) > 1 else "jobs"
ARMS = ("context", "sgrep", "probe-keyword", "probe-agent", "graphify", "oracle", "nop")
JOB = re.compile(r"^(%s)-(.+)-\d{8}-\d{6}$" % "|".join(re.escape(a) for a in ARMS))


def main():
    runs = collections.defaultdict(lambda: collections.defaultdict(list))  # arm -> task -> rewards
    failed = collections.Counter()
    for res in sorted(glob.glob(os.path.join(JOBS, "*", "*", "result.json"))):
        trial = os.path.dirname(res)
        m = JOB.match(os.path.basename(os.path.dirname(trial)))
        if not m:
            continue
        arm, task = m.groups()
        rw = os.path.join(trial, "verifier", "reward.txt")
        reward = float(open(rw).read().strip() or 0) if os.path.exists(rw) else None
        if reward is None or (json.load(open(res)).get("exception_info")):
            failed[arm] += 1
        runs[arm][task].append(reward or 0.0)
    if not runs:
        sys.exit(f"no trials in {JOBS}: run ./run.sh ARM TASK first")

    mean = lambda xs: sum(xs) / len(xs)
    share = lambda arm, tasks: mean([mean(runs[arm][t]) for t in tasks])
    print(f"{'arm':14s} {'trials':>6s} {'issues':>6s} {'failed':>6s} {'needed file first':>17s}")
    for arm in ARMS:
        if arm in runs:
            n = sum(len(v) for v in runs[arm].values())
            print(f"{arm:14s} {n:6d} {len(runs[arm]):6d} {failed[arm]:6d} {100 * share(arm, runs[arm]):16.0f}%")

    if "context" in runs:
        print(f"\nByteAsk Context vs each arm, on the issues both ran:")
        print(f"{'arm':14s} {'issues':>6s} {'ByteAsk Context':>15s} {'arm':>5s} {'difference':>11s}")
        for arm in ARMS:
            both = sorted(set(runs["context"]) & set(runs.get(arm, {})))
            if arm == "context" or not both:
                continue
            c, o = 100 * share("context", both), 100 * share(arm, both)
            print(f"{arm:14s} {len(both):6d} {c:14.0f}% {o:4.0f}% {c - o:+8.0f} pts")


if __name__ == "__main__":
    main()
