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
