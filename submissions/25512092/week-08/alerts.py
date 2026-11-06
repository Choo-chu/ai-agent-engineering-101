"""Messages for the person: urgent alerts and the once-a-day summary.

Every message goes to logs/alerts.jsonl and the console (the kit log). If a Telegram bot is configured it also
goes to Telegram. The bot token and chat id are read only from the environment variables TELEGRAM_BOT_TOKEN and
TELEGRAM_CHAT_ID (on Windows also from the user's saved environment, HKCU\\Environment, so `setx` works without
restarting the kit). They are never written to a file, a log or a commit; error messages are cut before any URL.
Without them, file + console only.

The same alert key is sent at most once per REPEAT_S.
"""
import json
import os
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "logs", "alerts.jsonl")
REPEAT_S = 3600
_sent = {}


def _env(name):
    v = os.environ.get(name)
    if v:
        return v
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
            return winreg.QueryValueEx(k, name)[0] or None
    except Exception:
        return None


def _seen(key):
    """Repeat guard across processes: the last time this key went out, from alerts.jsonl."""
    if key in _sent:
        return _sent[key]
    last = 0
    try:
        with open(PATH, encoding="utf-8") as f:
            for line in f:
                if f'"key": "{key}"' in line:
                    try:
                        last = max(last, json.loads(line)["ts"])
                    except (ValueError, KeyError):
                        pass
    except OSError:
        pass
    return last


def telegram(text):
    token, chat = _env("TELEGRAM_BOT_TOKEN"), _env("TELEGRAM_CHAT_ID")
    if not token or not chat:
        return "off"
    try:
        import httpx
        r = httpx.post(f"https://api.telegram.org/bot{token}/sendMessage",
                       data={"chat_id": chat, "text": text[:4000]}, timeout=15)
        return "sent" if r.status_code == 200 else f"http {r.status_code}"
    except Exception as e:
        return f"failed: {type(e).__name__}"             # never the exception text: it can carry the URL


def send(level, key, text, log=print):
    """level: urgent | daily | info. Returns the Telegram status (off / sent / ...) or 'repeat'."""
    now = time.time()
    if level != "daily" and now - _seen(key) < REPEAT_S:
        return "repeat"
    _sent[key] = now
    tg = telegram(f"[Choo Shop {level}] {text}")
    try:
        with open(PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": round(now, 1), "level": level, "key": key, "text": text, "telegram": tg},
                               ensure_ascii=False) + "\n")
    except OSError:
        pass
    log(f"[alert] {level} {key}: {text} (telegram {tg})")
    return tg


KEEPALIVE_LOG = os.path.join(HERE, "logs", "keepalive.log")
SEEN = os.path.join(HERE, "logs", "alerts_seen.json")


def cap_review(seen, log=print, now=None):
    """24 h after a STOCK_CAP change, once: sales in the 24 h after vs the 24 h before, and stock at cost at the
    change vs 24 h later. Sales not up while stock grew -> urgent alert."""
    import sales_report
    from market_db import connect
    now = now or time.time()
    c = sales_report.cap_change()
    if not c or now < c[0] + 86400 or seen.get("cap_review") == c[0]:
        return None
    db = connect()
    try:
        cc = sales_report.cap_compare(db, c[0] + 86400, max_h=24)
    finally:
        db.close()
    seen["cap_review"] = c[0]
    b, a = cc["before"], cc["after"]
    grew = a["stock_end"] is not None and a["stock_start"] is not None and a["stock_end"] > a["stock_start"]
    text = (f"STOCK_CAP {c[1]:,}, 24 h after vs before: sold {b['sales']} -> {a['sales']}, revenue {b['revenue']:,} -> "
            f"{a['revenue']:,}; stock at cost {a['stock_start']} -> {a['stock_end']}")
    import decisions
    if a["sales"] <= b["sales"] and grew:
        decisions.record("qc", "cap_review", "STOCK_CAP", c[1], "sales not up, stock grew: " + text)
        return send("urgent", f"cap_review:{c[0]}", "sales did not rise but stock grew after the cap change. " + text, log)
    decisions.record("qc", "cap_review", "STOCK_CAP", c[1], "ok: " + text)
    log(f"[alert] cap review ok: {text}")
    return "ok"


def watch(reports=None, log=print):
    """Called by restock.py every minute: urgent issues in the department reports, and new keepalive.log lines
    (kit restarted, public card not answering twice or more in a row)."""
    try:
        seen = json.load(open(SEEN, encoding="utf-8"))
    except (OSError, ValueError):
        seen = {"keepalive_lines": None}
    try:
        lines = open(KEEPALIVE_LOG, encoding="utf-8").read().splitlines()
    except OSError:
        lines = []
    start = seen.get("keepalive_lines")
    if start is None:
        start = len(lines)                             # first run: only lines from now on
    for ln in lines[start:]:
        if "kit started" in ln:
            send("urgent", "kit_restart", f"keepalive restarted the kit: {ln[:160]}", log)
        elif "not answering (2/" in ln or "not answering (3/" in ln:
            send("urgent", "shop_offline", f"public shop card not answering: {ln[:160]}", log)
    seen["keepalive_lines"] = len(lines)
    try:
        cap_review(seen, log)
    except Exception as e:
        log(f"[alert] cap review: {type(e).__name__}")
    try:
        seller_check(seen, log)
    except Exception as e:
        log(f"[alert] seller check: {type(e).__name__}")
    for dept, r in (reports or {}).items():
        for i in r.get("issues", []):
            if i.get("level") == "urgent":
                send("urgent", f"dept:{dept}:{i['text'][:30]}", f"{dept}: {i['text']}", log)
    try:
        with open(SEEN, "w", encoding="utf-8") as f:
            json.dump(seen, f)
    except OSError:
        pass


UTIL_ALERT = 0.70        # seller busy share in the last full hour (decision 11/06: tell the person above 70%)


def seller_utilization(now=None):
    """Share of the last full hour the seller spent inside harness calls (estimate). The seller calls the harness
    synchronously, one at a time; each '[seller] [harness]' line is one finished call. Call length = the median gap
    between back-to-back answers (gaps under 20 s) in that hour, so busy share = calls x that length / 3600."""
    import glob
    import re
    now = now or time.time()
    h1 = now // 3600 * 3600
    h0 = h1 - 3600
    files = sorted(glob.glob(os.path.join(HERE, "logs", "kit-console-*.txt")), key=os.path.getmtime)
    if not files:
        return None
    path = files[-1]
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        f.seek(max(0, size - 4_000_000))             # the last ~4 MB covers more than an hour
        tail = f.read().decode("utf-8", errors="replace").splitlines()
    day0 = time.localtime(h0)
    base = time.mktime((day0.tm_year, day0.tm_mon, day0.tm_mday, 0, 0, 0, 0, 0, -1))
    ts = []
    for ln in tail:
        m = re.match(r"(\d\d):(\d\d):(\d\d) \[seller\] \[harness\]", ln)
        if m:
            t = base + int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
            if h0 <= t < h1:
                ts.append(t)
    if len(ts) < 2:
        return {"hour": h0, "calls": len(ts), "call_s": None, "busy": 0.0}
    gaps = sorted(b - a for a, b in zip(ts, ts[1:]) if 0 < b - a < 20)
    call_s = gaps[len(gaps) // 2] if gaps else 6.5
    return {"hour": h0, "calls": len(ts), "call_s": call_s, "busy": min(1.0, len(ts) * call_s / 3600)}


def seller_check(seen, log=print):
    """Once per hour: alert when the seller was busy more than UTIL_ALERT of the last full hour."""
    h = time.time() // 3600 * 3600 - 3600
    if seen.get("util_hour") == h:
        return None
    seen["util_hour"] = h
    u = seller_utilization()
    if not u:
        return None
    import decisions
    decisions.record("qc", "seller_util", time.strftime("%m-%d %H:00", time.localtime(u["hour"])), round(u["busy"], 3),
                     f"{u['calls']} harness calls x {u['call_s']} s")
    if u["busy"] > UTIL_ALERT:
        return send("urgent", f"seller_util:{int(u['hour'])}",
                    f"seller busy {u['busy']:.0%} of {time.strftime('%H:00', time.localtime(u['hour']))} "
                    f"({u['calls']} harness calls x ~{u['call_s']} s, one at a time): consider concurrent harness calls",
                    log)
    return u
