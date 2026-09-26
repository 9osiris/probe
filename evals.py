import json

CHECK_TYPES = ("contains", "exact", "regex")


def load_evals(path):
    with open(path) as f:
        raw = json.load(f)
    if not isinstance(raw, list):
        raise ValueError("evals file must be a json list, got %s" % type(raw).__name__)
    evals = []
    for i, item in enumerate(raw):
        where = "eval #%d" % i
        if not isinstance(item, dict):
            raise ValueError("%s: must be an object" % where)
        name = item.get("name")
        if not name:
            raise ValueError("%s: missing name" % where)
        where = "eval %r" % name
        # turns wins over prompt, prompt wins over messages
        if "turns" in item:
            turns = item["turns"]
            if (not isinstance(turns, list) or not turns
                    or not all(isinstance(t, str) for t in turns)):
                raise ValueError("%s: turns must be a non-empty list of strings" % where)
            messages = []
            user_turns = [{"role": "user", "content": t} for t in turns]
        elif "prompt" in item:
            messages = [{"role": "user", "content": item["prompt"]}]
            user_turns = None
        elif "messages" in item:
            messages = item["messages"]
            user_turns = None
        else:
            raise ValueError("%s: needs prompt, messages, or turns" % where)
        if not isinstance(messages, list) or (not messages and user_turns is None):
            raise ValueError("%s: messages must be a non-empty list" % where)
        system = item.get("system")
        if system:
            messages = [{"role": "system", "content": system}] + messages
        check = item.get("check")
        if not isinstance(check, dict):
            raise ValueError("%s: missing check object" % where)
        if check.get("type") not in CHECK_TYPES:
            raise ValueError("%s: check type must be one of %s" % (where, CHECK_TYPES))
        if "value" not in check:
            raise ValueError("%s: check needs a value" % where)
        evals.append({"name": name, "messages": messages, "turns": user_turns, "check": check})
    if not evals:
        raise ValueError("no evals found in %s" % path)
    return evals
