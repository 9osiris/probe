import json
import os
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from checks import run_check
from evals import load_evals

passed = failed = 0


def check(name, cond):
    global passed, failed
    print(("ok   " if cond else "FAIL ") + name)
    if cond:
        passed += 1
    else:
        failed += 1


# check types, no server needed
check("contains hit", run_check({"type": "contains", "value": "recurs"}, "it recurses"))
check("contains miss", not run_check({"type": "contains", "value": "zzz"}, "it recurses"))
check("exact trims whitespace", run_check({"type": "exact", "value": "4"}, "  4\n"))
check("exact miss", not run_check({"type": "exact", "value": "4"}, "four"))
check("regex hit", run_check({"type": "regex", "value": "^\\d+\\.\\d+$"}, "3.6"))
check("regex miss", not run_check({"type": "regex", "value": "^\\d+\\.\\d+$"}, "three point six"))
try:
    run_check({"type": "bogus", "value": "x"}, "reply text")
    check("bad check type raises", False)
except ValueError:
    check("bad check type raises", True)


# eval file loading
def write_json(obj):
    f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
    json.dump(obj, f)
    f.close()
    return f.name


good = write_json([{"name": "a", "prompt": "hi", "check": {"type": "contains", "value": "x"}}])
check("loads prompt shorthand", load_evals(good)[0]["messages"] == [{"role": "user", "content": "hi"}])

full = write_json([{"name": "b", "system": "s", "messages": [{"role": "user", "content": "q"}],
                   "check": {"type": "exact", "value": "a"}}])
ev = load_evals(full)[0]
check("system prepended", ev["messages"][0] == {"role": "system", "content": "s"})

for bad, name in [
    ([{"prompt": "x", "check": {"type": "contains", "value": "x"}}], "missing name"),
    ([{"name": "x", "check": {"type": "contains", "value": "x"}}], "missing prompt"),
    ([{"name": "x", "prompt": "x", "check": {"type": "bogus", "value": "x"}}], "bad check type"),
    ({"name": "x"}, "not a list"),
    ([], "empty list"),
]:
    try:
        load_evals(write_json(bad))
        check("rejects %s" % name, False)
    except ValueError:
        check("rejects %s" % name, True)


# fake openai-compatible server
REPLIES = {}


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        last_user = [m for m in body["messages"] if m["role"] == "user"][-1]["content"]
        reply = REPLIES.get(last_user, "default reply")
        payload = {"choices": [{"message": {"role": "assistant", "content": reply}}]}
        data = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


server = HTTPServer(("127.0.0.1", 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
base = "http://127.0.0.1:%d/v1" % server.server_port


def run_cli(evals_path, replies):
    global REPLIES
    REPLIES = replies
    env = dict(os.environ, PROBE_BASE_URL=base, PROBE_API_KEY="test")
    p = subprocess.run([sys.executable, "main.py", "--evals", evals_path],
                       capture_output=True, text=True, env=env,
                       cwd=os.path.dirname(os.path.abspath(__file__)))
    return p


# all-pass run through the real cli
evals_path = write_json([
    {"name": "contains eval", "prompt": "q1", "check": {"type": "contains", "value": "needle"}},
    {"name": "exact eval", "prompt": "q2", "check": {"type": "exact", "value": "yes"}},
    {"name": "regex eval", "prompt": "q3", "check": {"type": "regex", "value": "^v\\d+$"}},
])
p = run_cli(evals_path, {"q1": "haystack has a needle in it", "q2": "yes", "q3": "v12"})
check("all pass exits 0", p.returncode == 0)
check("table shows 3 PASS", p.stdout.count("PASS") == 3)
check("summary 3/3", "3/3 passed" in p.stdout)

# one failing eval
p = run_cli(evals_path, {"q1": "no match here", "q2": "yes", "q3": "v12"})
check("one fail exits 1", p.returncode == 1)
check("table marks it FAIL", "contains eval" in p.stdout and "FAIL" in p.stdout)
check("summary 2/3", "2/3 passed" in p.stdout)

# bad evals file -> exit 2
p = run_cli(write_json([{"name": "x"}]), {})
check("bad evals file exits 2", p.returncode == 2)

# request shape sanity: model name forwarded
seen = {}


class SpyHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers["Content-Length"])
        body = json.loads(self.rfile.read(length))
        seen["model"] = body.get("model")
        seen["messages"] = body.get("messages")
        # same canned reply logic as Handler, body already consumed
        last_user = [m for m in body["messages"] if m["role"] == "user"][-1]["content"]
        reply = REPLIES.get(last_user, "default reply")
        payload = {"choices": [{"message": {"role": "assistant", "content": reply}}]}
        data = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


spy = HTTPServer(("127.0.0.1", 0), SpyHandler)
threading.Thread(target=spy.serve_forever, daemon=True).start()
spy_base = "http://127.0.0.1:%d/v1" % spy.server_port
env = dict(os.environ, PROBE_BASE_URL=spy_base, PROBE_API_KEY="test")
subprocess.run([sys.executable, "main.py", "--model", "fake-model-x", "--evals", evals_path],
               capture_output=True, env=env,
               cwd=os.path.dirname(os.path.abspath(__file__)))
check("model name forwarded", seen.get("model") == "fake-model-x")
check("messages forwarded", isinstance(seen.get("messages"), list) and len(seen["messages"]) == 1)

server.shutdown()
spy.shutdown()

print("\n%d passed, %d failed" % (passed, failed))
sys.exit(1 if failed else 0)
