# probe

score a model on benchmark prompts. point it at any openai-compatible
chat completions api, hand it a json file of evals, get a pass/fail table.

## run

```
python main.py --evals example_evals.json
python main.py --model gpt-4o --base-url http://localhost:8000/v1 --evals my_evals.json
```

flags can also come from env: `PROBE_MODEL`, `PROBE_BASE_URL`, `PROBE_API_KEY`.
exits 0 if everything passes, 1 if anything fails, 2 on bad input.

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

## notes

- stdlib only, no install
- one request per eval, sequential
- api errors mark that eval failed instead of crashing the run
