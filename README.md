# probe

score a model on benchmark prompts. point it at any openai-compatible
chat completions api, hand it a json file of evals, get a pass/fail table.

## run

```
python main.py --evals example_evals.json
python main.py --model gpt-4o --base-url http://localhost:8000/v1 --evals my_evals.json
```

flags can also come from env: `PROBE_MODEL`, `PROBE_BASE_URL`, `PROBE_API_KEY`,
`PROBE_TIMEOUT`.
exits 0 if everything passes, 1 if anything fails, 2 on bad input.

more flags:

- `--timeout SECONDS` - per-request timeout, default 120. a request that
  takes longer marks its eval failed with a timeout error.
- `--jobs N` - run N evals in parallel, default 1. output order always
  matches the evals file order.
- `--json` - print machine-readable json instead of the pass/fail table.
- `--filter TEXT` - only run evals whose name contains TEXT
  (case-insensitive). handy for rerunning one failing eval while you
  fix a prompt. exits 2 if nothing matches.

output looks like:

```
python reverse string       PASS
follow one-word instruction FAIL
3/4 passed
```

## writing evals

a json list. each eval needs a name, a prompt (or a full messages list,
plus an optional system prompt), and a check:

```json
[
  {
    "name": "one word answer",
    "system": "answer in one word",
    "prompt": "what is 2 + 2?",
    "check": {"type": "exact", "value": "4"}
  },
  {
    "name": "mentions recursion",
    "prompt": "explain quicksort briefly",
    "check": {"type": "contains", "value": "recursi"}
  },
  {
    "name": "version format",
    "prompt": "what python version added f-strings? just the number",
    "check": {"type": "regex", "value": "^\\s*3\\.6(\\.\\d+)?\\s*$"}
  }
]
```

check types: `contains` (substring), `exact` (whole reply, trimmed),
`regex` (re.search on the reply).

## multi-turn evals

an eval can use `turns` instead of `prompt`/`messages`: a list of user
messages sent one at a time, each with the full conversation history so
far. the check applies to the final reply.

```json
[
  {
    "name": "remembers the topic",
    "system": "you are a helpful assistant",
    "turns": ["i like blue", "what color did i just mention?"],
    "check": {"type": "contains", "value": "blue"}
  }
]
```

## notes

- stdlib only, no install
- one request per eval, sequential unless --jobs is raised
- api errors and timeouts mark that eval failed instead of crashing the run
