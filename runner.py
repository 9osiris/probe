import time
from concurrent.futures import ThreadPoolExecutor

from checks import run_check


def run_one(ev, client):
    # one eval, returns its result dict
    start = time.perf_counter()
    try:
        if ev["turns"] is not None:
            # multi-turn: send each user turn with the full history so far,
            # the check applies to the final reply
            history = list(ev["messages"])
            reply = ""
            for turn in ev["turns"]:
                history.append(turn)
                reply = client.complete(history)
                history.append({"role": "assistant", "content": reply})
        else:
            reply = client.complete(ev["messages"])
        passed = run_check(ev["check"], reply)
        result = {"name": ev["name"], "passed": passed, "reply": reply}
    except Exception as e:
        result = {"name": ev["name"], "passed": False, "error": str(e)}
    result["ms"] = int((time.perf_counter() - start) * 1000)
    return result


def run_evals(evals, client, jobs=1, fail_fast=False):
    # jobs > 1 runs evals on a thread pool; results stay in input order
    # fail_fast stops after the first failure and marks the rest skipped,
    # which only makes sense serially, so it overrides jobs
    if fail_fast:
        results = []
        for ev in evals:
            result = run_one(ev, client)
            results.append(result)
            if not result["passed"]:
                for rest in evals[len(results):]:
                    results.append({"name": rest["name"], "passed": False,
                                    "skipped": True, "ms": 0})
                break
        return results
    if jobs <= 1:
        return [run_one(ev, client) for ev in evals]
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        return list(pool.map(lambda ev: run_one(ev, client), evals))
