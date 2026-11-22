#!/usr/bin/env python3
"""An OpenAI-compatible /v1/chat/completions endpoint on 127.0.0.1:8900 that answers with `claude -p`.

    python shim/claude_shim.py                       (SHIM_MODEL=sonnet by default)
    agent.json "llm": {"base": "http://127.0.0.1:8900/v1", "model": "claude-shim", "key_env": "..."}

What the kit sends (scripts/round4/agent_kit.py, Model.complete): POST <base>/chat/completions with
{"model", "messages": [{"role": "system"|"user"|"assistant", "content": str}], "max_tokens"}; it reads
choices[0].message.content. Its socket read times out after 60 s of silence and the whole call after 180 s.

Each request runs one fresh `claude -p` in the empty folder shim/workdir with no tools, no MCP servers, no settings
files, no CLAUDE.md and no auto-memory; the system messages become --system-prompt and the rest of the conversation is
sent on stdin as text. A pool keeps SHIM_POOL (default 2) processes per (model, system prompt) started and waiting for
their stdin, so a request does not pay the start-up; each one taken is replaced at once.

Claude Code still adds the signed-in account's email and this machine's paths to the context, and nothing short of
--bare (API keys only) turns that off. The agent writes public forum posts, so every answer is scrubbed of email
addresses and of the user-profile path before it goes back to the kit.

Environment: SHIM_MODEL (sonnet), SHIM_POOL (2; 0 = no prewarm), SHIM_PORT (8900), SHIM_EFFORT (unset = CLI default),
SHIM_TIMEOUT (170 s per claude call). Log: shim/logs/shim.log, one line per request.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORKDIR = HERE / "workdir"
LOGDIR = HERE / "logs"
MODEL = os.environ.get("SHIM_MODEL", "sonnet")
POOL = int(os.environ.get("SHIM_POOL", "2"))
PORT = int(os.environ.get("SHIM_PORT", "8900"))
EFFORT = os.environ.get("SHIM_EFFORT", "")
TIMEOUT = float(os.environ.get("SHIM_TIMEOUT", "170"))
KEEPALIVE = 15                     # seconds between the whitespace bytes that keep the kit's 60 s socket timeout away
WARM_MAX_AGE = 600                 # a waiting process older than this is replaced (its session start is stale)
ARG_LIMIT = 24_000                 # Windows caps a command line near 32k characters; a longer system prompt goes on stdin
CLAUDE = shutil.which("claude") or "claude"

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
# C:\Users\<name> written with \, \\ (inside JSON) or /
HOME = re.compile(r"[\\/]+".join(re.escape(p) for p in re.split(r"[\\/]+", str(Path.home())) if p), re.I)

ENV = dict(os.environ, CLAUDE_CODE_DISABLE_AUTO_MEMORY="1", CLAUDE_CODE_DISABLE_CLAUDE_MDS="1")

_log_lock = threading.Lock()


def log(**kv):
    LOGDIR.mkdir(parents=True, exist_ok=True)
    line = time.strftime("%m-%d %H:%M:%S ") + " ".join(f"{k}={v}" for k, v in kv.items())
    with _log_lock, open(LOGDIR / "shim.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(line, flush=True)


def scrub(text):
    return HOME.sub("~", EMAIL.sub("[email]", text))


def command(model, system):
    # stream-json input: a plain-text `claude -p` gives up after 3 s without stdin, so it cannot wait in the pool;
    # in stream-json mode it waits for the message line, and closing stdin ends the session after one answer.
    cmd = [CLAUDE, "-p", "--model", model, "--input-format", "stream-json", "--output-format", "stream-json",
           "--verbose", "--tools", "", "--strict-mcp-config", "--setting-sources", "", "--disable-slash-commands",
           "--no-session-persistence"]
    if EFFORT:
        cmd += ["--effort", EFFORT]
    if system and len(system) <= ARG_LIMIT:
        cmd += ["--system-prompt", system]
    else:
        cmd += ["--system-prompt", "Follow the instructions at the start of the user's message."]
    return cmd


def spawn(model, system):
    WORKDIR.mkdir(parents=True, exist_ok=True)
    p = subprocess.Popen(command(model, system), cwd=WORKDIR, env=ENV, stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    p.started = time.time()
    return p


class Pool:
    """SHIM_POOL processes per (model, system prompt), each started and waiting for its stdin."""

    def __init__(self, size):
        self.size, self.lock, self.idle = size, threading.Lock(), {}

    def take(self, model, system):
        key = (model, hashlib.sha256(system.encode()).hexdigest())
        proc = None
        with self.lock:
            q = self.idle.setdefault(key, [])
            while q:
                p = q.pop(0)
                if p.poll() is None and time.time() - p.started < WARM_MAX_AGE:
                    proc = p
                    break
                p.kill()
        warm = proc is not None
        if not warm:
            proc = spawn(model, system)
        if self.size:
            threading.Thread(target=self.fill, args=(key, model, system), daemon=True).start()
        return proc, warm

    def fill(self, key, model, system):
        with self.lock:
            need = self.size - len(self.idle.get(key, []))
        for _ in range(max(0, need)):
            p = spawn(model, system)
            with self.lock:
                self.idle.setdefault(key, []).append(p)


POOL_ = Pool(POOL)


def to_prompt(messages):
    system = "\n\n".join(m.get("content") or "" for m in messages if m.get("role") == "system")
    turns = [m for m in messages if m.get("role") != "system"]
    parts = ["The conversation so far is below. Write only the next assistant message, exactly in the format the "
             "system prompt asks for, with nothing before or after it.\n"]
    for m in turns:
        role = "assistant" if m.get("role") == "assistant" else "user"
        content = m.get("content")
        if isinstance(content, list):                  # OpenAI content parts
            content = "".join(c.get("text", "") for c in content if isinstance(c, dict))
        parts.append(f"<{role}>\n{content or ''}\n</{role}>")
    parts.append("<assistant>")
    body = "\n\n".join(parts)
    if system and len(system) > ARG_LIMIT:
        body = f"<instructions>\n{system}\n</instructions>\n\n" + body
    return system, body


def ask(messages):
    """Returns (content, info). Raises on failure."""
    system, body = to_prompt(messages)
    t0 = time.time()
    proc, warm = POOL_.take(MODEL, system)
    waited = time.time() - proc.started
    line = json.dumps({"type": "user", "message": {"role": "user", "content": body}}, ensure_ascii=False) + "\n"
    try:
        out, err = proc.communicate(line.encode("utf-8"), timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        proc.kill()
        raise TimeoutError(f"claude -p did not answer within {TIMEOUT:.0f} s")
    res, limit = None, None
    for raw in out.decode("utf-8", "replace").splitlines():
        try:
            ev = json.loads(raw)
        except ValueError:
            continue
        if ev.get("type") == "result":
            res = ev
        elif ev.get("type") == "rate_limit_event":
            limit = ev.get("rate_limit_info") or {k: v for k, v in ev.items() if k not in ("type", "session_id", "uuid")}
    if res is None:
        raise RuntimeError(f"claude -p exited {proc.returncode} without a result: {err.decode('utf-8', 'replace')[-300:]}")
    if res.get("is_error"):
        raise RuntimeError(f"claude -p error: {str(res.get('result'))[:300]}")
    text = res.get("result") or ""
    text = re.sub(r"\s*</assistant>\s*$", "", text.strip())
    usage = res.get("usage") or {}
    info = {"warm": warm, "warm_age_s": round(waited, 1), "total_s": round(time.time() - t0, 2),
            "api_ms": res.get("duration_api_ms"), "in_chars": len(system) + len(body),
            "out_chars": len(text), "in_tok": (usage.get("input_tokens") or 0) + (usage.get("cache_read_input_tokens") or 0)
            + (usage.get("cache_creation_input_tokens") or 0), "out_tok": usage.get("output_tokens") or 0}
    if limit:
        info["rate_limit"] = json.dumps(limit, ensure_ascii=False, separators=(",", ":"))
    return scrub(text), info


def json_move_ok(text):
    """The kit's FORMAT: one JSON object with thought, action, args, and nothing else."""
    try:
        obj = json.loads(text.strip())
    except ValueError:
        return False
    return isinstance(obj, dict) and {"thought", "action", "args"} <= set(obj)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"                       # the body ends when the connection closes: no length needed

    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.rstrip("/").endswith("/models"):
            return self.send_json({"object": "list", "data": [{"id": MODEL, "object": "model", "owned_by": "claude-shim"}]})
        self.send_json({"ok": True, "model": MODEL, "pool": POOL})

    def send_json(self, obj, code=200):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        if not self.path.rstrip("/").endswith("/chat/completions"):
            return self.send_json({"error": {"message": "not found"}}, 404)
        try:
            req = json.loads(self.rfile.read(int(self.headers.get("content-length") or 0)) or b"{}")
            messages = req["messages"]
        except (ValueError, KeyError, TypeError) as e:
            return self.send_json({"error": {"message": f"bad request: {e}"}}, 400)
        rid = uuid.uuid4().hex[:12]
        # Headers now, then a space every KEEPALIVE s while claude works (leading whitespace is valid JSON).
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.end_headers()
        box, done = {}, threading.Event()

        def work():
            try:
                box["out"] = ask(messages)
            except Exception as e:
                box["err"] = e
            done.set()
        threading.Thread(target=work, daemon=True).start()
        try:
            while not done.wait(KEEPALIVE):
                self.wfile.write(b" ")
                self.wfile.flush()
        except OSError:
            pass                                          # the kit gave up; the answer is still logged
        if "err" in box:
            e = box["err"]
            log(id=rid, model=MODEL, ok=False, error=json.dumps(f"{type(e).__name__}: {e}"[:300], ensure_ascii=False))
            body = {"error": {"message": f"{type(e).__name__}: {e}"}}
        else:
            text, info = box["out"]
            log(id=rid, model=MODEL, ok=True, json_ok=json_move_ok(text), turns=len(messages), **info)
            body = {"id": "chatcmpl-" + rid, "object": "chat.completion", "created": int(time.time()), "model": MODEL,
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": info["in_tok"], "completion_tokens": info["out_tok"],
                              "total_tokens": info["in_tok"] + info["out_tok"]}}
        try:
            self.wfile.write(json.dumps(body, ensure_ascii=False).encode("utf-8"))
        except OSError:
            pass


def main():
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    log(event="start", model=MODEL, pool=POOL, effort=EFFORT or "default", port=PORT, claude=json.dumps(CLAUDE))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        for q in POOL_.idle.values():
            for p in q:
                p.kill()


if __name__ == "__main__":
    main()
