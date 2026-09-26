import re


def run_check(check, reply):
    kind = check["type"]
    value = check["value"]
    if kind == "contains":
        return value in reply
    if kind == "exact":
        return reply.strip() == value.strip()
    if kind == "regex":
        return re.search(value, reply) is not None
    raise ValueError("unknown check type: %r (want contains, exact, regex)" % kind)
