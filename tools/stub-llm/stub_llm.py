"""Deterministic OpenAI-compatible stub server for manual testing (no keys, no cost).

    python tools/stub-llm/stub_llm.py            # listens on http://127.0.0.1:9911

Point an "OpenAI-compatible endpoint" provider at one of these base URLs:

    http://127.0.0.1:9911/ok/v1        always answers "OK"
    http://127.0.0.1:9911/down/v1      always 503 (transient: retried, then fallback)
    http://127.0.0.1:9911/slow/v1      sleeps 30 s (exceeds the 20 s connection-test timeout)
    http://127.0.0.1:9911/ratelimit/v1 429 with Retry-After: 1
    http://127.0.0.1:9911/badkey/v1    401 invalid key (no fallback; provider marked)
    http://127.0.0.1:9911/nomodel/v1   404 model not found
    http://127.0.0.1:9911/noquota/v1   429 insufficient_quota

From the Docker stack use host.docker.internal instead of 127.0.0.1 and start the stub with
``--host 0.0.0.0``. Test-only: never enable it in production configuration.
"""

import argparse
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ERRORS = {
    "down": (503, {"error": {"message": "Service temporarily unavailable"}}, {}),
    "ratelimit": (
        429,
        {"error": {"message": "Rate limit reached", "code": "rate_limit_exceeded"}},
        {"Retry-After": "1"},
    ),
    "badkey": (
        401,
        {"error": {"message": "Incorrect API key provided", "code": "invalid_api_key"}},
        {},
    ),
    "nomodel": (
        404,
        {"error": {"message": "The model does not exist", "code": "model_not_found"}},
        {},
    ),
    "noquota": (
        429,
        {"error": {"message": "You exceeded your current quota", "code": "insufficient_quota"}},
        {},
    ),
}


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, body: dict, headers: dict | None = None) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _mode(self) -> str:
        return self.path.strip("/").split("/", 1)[0]

    def do_GET(self) -> None:  # noqa: N802
        if self.path.endswith("/models"):
            self._send(200, {"data": [{"id": "stub-small"}, {"id": "stub-large"}]})
        else:
            self._send(404, {"error": {"message": "not found"}})

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        mode = self._mode()
        if mode == "slow":
            time.sleep(30)
        if mode in ERRORS:
            status, payload, headers = ERRORS[mode]
            return self._send(status, payload, headers)
        if not self.path.endswith("/chat/completions"):
            return self._send(404, {"error": {"message": "not found"}})
        wants_json = (body.get("response_format") or {}).get("type") == "json_object"
        self._send(
            200,
            {
                "model": body.get("model", "stub"),
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "{}" if wants_json else "OK"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 12, "completion_tokens": 1},
            },
        )

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"stub-llm: {self.command} {self.path} -> {args[1] if len(args) > 1 else ''}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9911)
    args = parser.parse_args()
    print(f"Stub LLM listening on http://{args.host}:{args.port} (see module docstring for URLs)")
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
