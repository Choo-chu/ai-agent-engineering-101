"""Supply window alarm for choo-chu. At opens_at + 5 s it sends one message per window to the owner's app chat
(POST 127.0.0.1:8800/api/chat), which wakes the agent. The access code is read from .kit/app.key and never printed.

    python analysis/window_alarm.py
"""
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

MARKET = "https://market.ourolabs.ai"
APP = "http://127.0.0.1:8800"
ROOT = Path(__file__).resolve().parent.parent          # submissions/25512092/round-4
STATE = ROOT / "analysis" / "data" / "alarm_state.json"
UA = {"user-agent": "Mozilla/5.0 (compatible; window-alarm)"}


def hms(t):
    return time.strftime("%H:%M:%S", time.localtime(t))


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def window():
    req = urllib.request.Request(MARKET + "/api/restock", headers=UA)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def send(text):
    key = (ROOT / ".kit" / "app.key").read_text(encoding="utf-8").strip()
    body = json.dumps({"text": text, "user": "사장 알람"}).encode()
    head = {"content-type": "application/json", "cookie": "miniapp_access=" + key}
    req = urllib.request.Request(APP + "/api/chat", data=body, headers=head)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return f"sent ({r.status})"
    except TimeoutError:
        return "sent (agent still answering)"         # the message is delivered before the reply wait
    except urllib.error.URLError as e:
        if isinstance(e.reason, TimeoutError):
            return "sent (agent still answering)"
        raise


def load_done():
    try:
        return set(json.loads(STATE.read_text(encoding="utf-8")))
    except Exception:
        return set()


def save_done(done):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(sorted(done)[-200:]), encoding="utf-8")


def main():
    done = load_done()
    told = None
    while True:
        try:
            w = window()
            opens, closes, now = float(w["opens_at"]), float(w["closes_at"]), time.time()
            if told != opens:
                log(f"next window {hms(opens)} ~ {hms(closes)}")
                told = opens
            key = str(int(opens))
            if key not in done and opens + 5 <= now < closes - 20:
                text = f"공급 창 열림(닫힘 {hms(closes)}). 다른 일 멈추고 메모 1번대로 restock_list 지금 실행."
                log(f"alarm for {hms(opens)}: " + send(text))
                done.add(key)
                save_done(done)
                time.sleep(30)
                continue
            wait = opens + 5 - now if now < opens + 5 else 30
            time.sleep(max(1, min(wait, 60)))
        except Exception as e:                             # never die: log the type and try again
            log(f"error: {type(e).__name__}")
            time.sleep(15)


if __name__ == "__main__":
    main()
