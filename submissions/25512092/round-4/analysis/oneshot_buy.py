"""One-shot owner order for choo-chu. Picks ONE supply window (the next one, or --opens <epoch>), waits until it is open,
sends one message to the owner's app chat (POST 127.0.0.1:8800/api/chat) telling the agent to run restock_list with
the list below, then exits. It never sends twice and never moves on to a later window. The access code is read from
.kit/app.key and never printed.

    python analysis/oneshot_buy.py              # next window
    python analysis/oneshot_buy.py --dry-run    # print the plan and the message, send nothing
    python analysis/oneshot_buy.py --opens 1795618985
"""
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

MARKET = "https://market.ourolabs.ai"
APP = "http://127.0.0.1:8800"
ROOT = Path(__file__).resolve().parent.parent          # submissions/25512092/round-4
UA = {"user-agent": "Mozilla/5.0 (compatible; oneshot-buy)"}
ITEMS = [                                              # cheapest first so the cap drops the dearest lot, not the rest
    {"sku": "Ge27b5835", "qty": 2},                    # 친환경 무항생제 한돈 냉장 앞다리살 500g (list 7,800, shelf 24 h)
    {"sku": "G132d1e4e", "qty": 2},                    # 국내산 새우젓 1kg (list 9,900, shelf 168 h)
    {"sku": "G08cbcee7", "qty": 2},                    # 핸드드립커피 드립백커피 6개국 모듬 8g x 36 (list 26,900, shelf 720 h)
]
MAX_SPEND = 50000


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
    body = json.dumps({"text": text, "user": "사장"}).encode()
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


def main():
    dry = "--dry-run" in sys.argv
    target = int(sys.argv[sys.argv.index("--opens") + 1]) if "--opens" in sys.argv else None
    items = json.dumps(ITEMS, separators=(", ", ": "))
    text = f"사장 지시야. restock_list로 {items} 구매, max_spend {MAX_SPEND}. 이번 한 번만."
    while True:
        try:
            w = window()
            break
        except Exception as e:
            log(f"error: {type(e).__name__}, retry")
            time.sleep(10)
    opens, closes = int(w["opens_at"]), int(w["closes_at"])
    if target and target != opens:
        log(f"the market's window is {opens} ({hms(opens)}), not {target}; nothing sent")
        return
    log(f"window {hms(opens)} ~ {hms(closes)}; message: {text}")
    if dry:
        log("dry run: nothing sent")
        return
    while time.time() < opens + 5:
        time.sleep(max(1, min(opens + 5 - time.time(), 30)))
    if time.time() >= closes - 20:
        log("window almost closed; nothing sent")
        return
    try:                                                 # one attempt only: a retry could order twice
        log("order: " + send(text))
    except Exception as e:
        log(f"not sent: {type(e).__name__}")


if __name__ == "__main__":
    main()
