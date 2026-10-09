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
check("regex hit", run_check({"type": "regex", "value": "^\d+\.\d+$"}, "3.6"))
check("regex miss", not run_check({"type": "regex", "value": "^\d+\.\d+$"}, "three point six"))
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
    {"name": "regex eval", "prompt": "q3", "check": {"type": "regex", "value": "^v\d+$"}},
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

# multi-turn evals: loader
t = write_json([{"name": "mt", "system": "s", "turns": ["q1", "q2"],
                 "check": {"type": "contains", "value": "x"}}])
ev = load_evals(t)[0]
check("turns loader builds user turns",
      ev["turns"] == [{"role": "user", "content": "q1"}, {"role": "user", "content": "q2"}])
check("turns loader keeps system as base",
      ev["messages"] == [{"role": "system", "content": "s"}])
for bad, name in [
    ([{"name": "x", "turns": [], "check": {"type": "contains", "value": "x"}}], "empty turns"),
    ([{"name": "x", "turns": [1, 2], "check": {"type": "contains", "value": "x"}}], "non-string turns"),
    ([{"name": "x", "turns": "not a list", "check": {"type": "contains", "value": "x"}}], "turns not a list"),
]:
    try:
        load_evals(write_json(bad))
        check("rejects %s" % name, False)
    except ValueError:
        check("rejects %s" % name, True)


# multi-turn run: check applies to final reply, history is sent
server2 = HTTPServer(("127.0.0.1", 0), Handler)
threading.Thread(target=server2.serve_forever, daemon=True).start()
base2 = "http://127.0.0.1:%d/v1" % server2.server_port


def run_cli2(evals_path, replies, extra=()):
    global REPLIES
    REPLIES = replies
    env = dict(os.environ, PROBE_BASE_URL=base2, PROBE_API_KEY="test")
    p = subprocess.run([sys.executable, "main.py", "--evals", evals_path] + list(extra),
                       capture_output=True, text=True, env=env,
                       cwd=os.path.dirname(os.path.abspath(__file__)))
    return p


mt_path = write_json([
    {"name": "multi", "turns": ["first", "second"], "check": {"type": "contains", "value": "done"}},
])
p = run_cli2(mt_path, {"first": "ack", "second": "all done"})
check("multi-turn passes on final reply", p.returncode == 0 and "1/1 passed" in p.stdout)
p = run_cli2(mt_path, {"first": "ack", "second": "not quite"})
check("multi-turn fails on final reply", p.returncode == 1 and "0/1 passed" in p.stdout)

# spy on the second request: it must carry the full history
seen2 = {}


class Spy2Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers["Content-Length"])
        body = json.loads(self.rfile.read(length))
        seen2.setdefault("calls", []).append(body["messages"])
        last_user = [m for m in body["messages"] if m["role"] == "user"][-1]["content"]
        reply = {"first": "ack", "second": "all done"}.get(last_user, "default reply")
        payload = {"choices": [{"message": {"role": "assistant", "content": reply}}]}
        data = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


spy2 = HTTPServer(("127.0.0.1", 0), Spy2Handler)
threading.Thread(target=spy2.serve_forever, daemon=True).start()
env = dict(os.environ, PROBE_BASE_URL="http://127.0.0.1:%d/v1" % spy2.server_port,
           PROBE_API_KEY="test")
subprocess.run([sys.executable, "main.py", "--evals", mt_path],
               capture_output=True, env=env,
               cwd=os.path.dirname(os.path.abspath(__file__)))
calls = seen2.get("calls", [])
check("multi-turn sends two requests", len(calls) == 2)
check("second request carries full history",
      len(calls) == 2 and [m["content"] for m in calls[1]]
      == ["first", "ack", "second"])
spy2.shutdown()
server2.shutdown()


# --timeout: slow server marks the eval failed instead of hanging
class SlowHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers["Content-Length"])
        self.rfile.read(length)
        import time as _time
        _time.sleep(2)
        payload = {"choices": [{"message": {"role": "assistant", "content": "too late"}}]}
        data = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, *a):
        pass


slow = HTTPServer(("127.0.0.1", 0), SlowHandler)
threading.Thread(target=slow.serve_forever, daemon=True).start()
slow_base = "http://127.0.0.1:%d/v1" % slow.server_port
to_path = write_json([{"name": "slow eval", "prompt": "q", "check": {"type": "contains", "value": "x"}}])
env = dict(os.environ, PROBE_BASE_URL=slow_base, PROBE_API_KEY="test")
p = subprocess.run([sys.executable, "main.py", "--evals", to_path, "--timeout", "0.3"],
                   capture_output=True, text=True, env=env,
                   cwd=os.path.dirname(os.path.abspath(__file__)))
check("timeout fails the eval", p.returncode == 1 and "0/1 passed" in p.stdout)
check("timeout error message shown", "timed out" in p.stdout)
slow.shutdown()


# --jobs: parallel runs keep input order even when later evals finish first
DELAYS = {}


class DelayHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        import time as _time
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        last_user = [m for m in body["messages"] if m["role"] == "user"][-1]["content"]
        _time.sleep(DELAYS.get(last_user, 0))
        payload = {"choices": [{"message": {"role": "assistant", "content": "r-" + last_user}}]}
        data = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


delay = HTTPServer(("127.0.0.1", 0), DelayHandler)
threading.Thread(target=delay.serve_forever, daemon=True).start()
delay_base = "http://127.0.0.1:%d/v1" % delay.server_port
DELAYS.update({"q1": 0.4, "q2": 0.3, "q3": 0.2, "q4": 0.0})
jobs_path = write_json([
    {"name": "job one", "prompt": "q1", "check": {"type": "contains", "value": "r-q1"}},
    {"name": "job two", "prompt": "q2", "check": {"type": "contains", "value": "r-q2"}},
    {"name": "job three", "prompt": "q3", "check": {"type": "contains", "value": "r-q3"}},
    {"name": "job four", "prompt": "q4", "check": {"type": "contains", "value": "r-q4"}},
])
env = dict(os.environ, PROBE_BASE_URL=delay_base, PROBE_API_KEY="test")
p = subprocess.run([sys.executable, "main.py", "--evals", jobs_path, "--jobs", "4"],
                   capture_output=True, text=True, env=env,
                   cwd=os.path.dirname(os.path.abspath(__file__)))
order = [n for n in ["job one", "job two", "job three", "job four"]
         if n in p.stdout]
check("parallel keeps input order", order == ["job one", "job two", "job three", "job four"])
check("parallel all pass", p.returncode == 0 and "4/4 passed" in p.stdout)
p = subprocess.run([sys.executable, "main.py", "--evals", jobs_path, "--jobs", "0"],
                   capture_output=True, text=True, env=env,
                   cwd=os.path.dirname(os.path.abspath(__file__)))
check("--jobs 0 rejected", p.returncode == 2)
delay.shutdown()


# --json: machine-readable output
server3 = HTTPServer(("127.0.0.1", 0), Handler)
threading.Thread(target=server3.serve_forever, daemon=True).start()
base3 = "http://127.0.0.1:%d/v1" % server3.server_port
env = dict(os.environ, PROBE_BASE_URL=base3, PROBE_API_KEY="test")
REPLIES = {"q1": "has needle", "q2": "nope"}
jp = write_json([
    {"name": "j1", "prompt": "q1", "check": {"type": "contains", "value": "needle"}},
    {"name": "j2", "prompt": "q2", "check": {"type": "contains", "value": "needle"}},
])
p = subprocess.run([sys.executable, "main.py", "--evals", jp, "--json"],
                   capture_output=True, text=True, env=env,
                   cwd=os.path.dirname(os.path.abspath(__file__)))
doc = json.loads(p.stdout)
check("json parses", isinstance(doc, dict))
check("json totals", doc.get("passed") == 1 and doc.get("total") == 2)
check("json result order", [r["name"] for r in doc["results"]] == ["j1", "j2"])
check("json pass flags", [r["passed"] for r in doc["results"]] == [True, False])
check("json has reply and ms", "reply" in doc["results"][0] and "ms" in doc["results"][0])
check("json failing eval keeps working", p.returncode == 1)
server3.shutdown()


# --filter: run only evals whose name matches
server4 = HTTPServer(("127.0.0.1", 0), Handler)
threading.Thread(target=server4.serve_forever, daemon=True).start()
base4 = "http://127.0.0.1:%d/v1" % server4.server_port
env = dict(os.environ, PROBE_BASE_URL=base4, PROBE_API_KEY="test")
REPLIES = {"q1": "has needle", "q2": "yes"}
fp = write_json([
    {"name": "string reverse", "prompt": "q1", "check": {"type": "contains", "value": "needle"}},
    {"name": "math basic", "prompt": "q2", "check": {"type": "exact", "value": "yes"}},
    {"name": "string upper", "prompt": "q1", "check": {"type": "contains", "value": "needle"}},
])
p = subprocess.run([sys.executable, "main.py", "--evals", fp, "--filter", "string"],
                   capture_output=True, text=True, env=env,
                   cwd=os.path.dirname(os.path.abspath(__file__)))
check("filter runs matching subset", p.returncode == 0 and "2/2 passed" in p.stdout)
check("filter skips non-matching", "math basic" not in p.stdout)
p = subprocess.run([sys.executable, "main.py", "--evals", fp, "--filter", "STRING"],
                   capture_output=True, text=True, env=env,
                   cwd=os.path.dirname(os.path.abspath(__file__)))
check("filter is case-insensitive", p.returncode == 0 and "2/2 passed" in p.stdout)
p = subprocess.run([sys.executable, "main.py", "--evals", fp, "--filter", "zzz"],
                   capture_output=True, text=True, env=env,
                   cwd=os.path.dirname(os.path.abspath(__file__)))
check("filter with no match exits 2", p.returncode == 2 and "no evals matched" in p.stderr)
p = subprocess.run([sys.executable, "main.py", "--evals", fp, "--filter", "math", "--json"],
                   capture_output=True, text=True, env=env,
                   cwd=os.path.dirname(os.path.abspath(__file__)))
doc = json.loads(p.stdout)
check("filter works with json output", doc.get("total") == 1 and doc["results"][0]["name"] == "math basic")
server4.shutdown()

print("\n%d passed, %d failed" % (passed, failed))
sys.exit(1 if failed else 0)
