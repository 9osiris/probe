from checks import run_check


def run_evals(evals, client):
    results = []
    for ev in evals:
        try:
            reply = client.complete(ev["messages"])
        except Exception as e:
            results.append({"name": ev["name"], "passed": False, "error": str(e)})
            continue
        passed = run_check(ev["check"], reply)
        results.append({"name": ev["name"], "passed": passed, "reply": reply})
    return results
