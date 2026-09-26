import json
import urllib.request
import urllib.error


class ChatClient:
    def __init__(self, base_url, api_key, model, timeout=120):
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def complete(self, messages):
        body = {"model": self.model, "messages": messages}
        req = urllib.request.Request(
            self.url,
            data=json.dumps(body).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + self.api_key,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                payload = json.load(resp)
        except TimeoutError:
            # socket.timeout is the same object since python 3.10
            raise RuntimeError("request timed out after %ss" % self.timeout)
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:500]
            raise RuntimeError("api error %d: %s" % (e.code, detail))
        return payload["choices"][0]["message"].get("content") or ""
