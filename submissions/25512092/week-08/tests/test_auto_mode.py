"""11/10 ~15:00 (person): auto mode - Telegram filter, warn-only brakes, the watchdog's restart rules, harness failure
streak. Temp files only.
    python tests/test_auto_mode.py"""
import json
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _isolate import tmp_json  # noqa: E402
import alerts  # noqa: E402

NOW = 1_000_000.0


def test_held():
    p = tmp_json({"enabled": True, "until": NOW + 10, "pass_keys": ["morning_summary"], "brakes_warn_only": True}, "am")
    with mock.patch.object(alerts, "AUTO_MODE", p):
        assert alerts.held("info", "x", NOW) and alerts.held("daily", "deep_high_report:1", NOW)
        assert not alerts.held("urgent", "x", NOW) and not alerts.held("daily", "morning_summary:20261110", NOW)
        assert not alerts.held("info", "x", NOW + 20)                  # after "until"
        assert alerts.brakes_warn_only(NOW) and not alerts.brakes_warn_only(NOW + 20)
        sent = []
        with mock.patch.object(alerts, "telegram", lambda t: sent.append(t) or "sent"), \
                mock.patch.object(alerts, "PATH", p + ".jsonl"), mock.patch("time.time", return_value=NOW):
            assert alerts.send("info", "k1", "t", log=lambda m: None) == "held"
            assert alerts.send("urgent", "k2", "t", log=lambda m: None) == "sent" and len(sent) == 1
    with mock.patch.object(alerts, "AUTO_MODE", p + ".missing"):
        assert not alerts.held("info", "x", NOW) and not alerts.brakes_warn_only(NOW)


def test_watchdog():
    import watchdog as W
    rows = [(1, 0, "python keepalive.py"), (2, 1, "python market_kit.py join"), (3, 2, "python seller_r3.py"),
            (4, 0, "python analyst_main.py")]
    calls = []
    with mock.patch.object(W, "urgent", lambda k, t: calls.append(k)), \
            mock.patch.object(W, "start_analyst", lambda: calls.append("start")), \
            mock.patch.object(W, "restart_kit", lambda r: calls.append("kit") or True):
        s = {}
        assert W.check(s, rows, NOW, 10) == []
        no_an = [r for r in rows if r[0] != 4]
        for i in range(3):
            assert "analyst restarted" in W.check(s, no_an, NOW + i * 60, 10)
        acts = W.check(s, no_an, NOW + 200, 10)                         # 4th within the hour: stopped
        assert "analyst restarted" not in acts and "watchdog_stop:analyst" in calls and calls.count("start") == 3
        no_seller = [r for r in rows if r[0] != 3]
        s = {}
        assert W.check(s, no_seller, NOW, 10) == ["seller down: x"] or "kit" not in calls[-1:]   # 1st miss: wait
        acts = W.check(s, no_seller, NOW + 60, 10)
        assert any("kit restarted (seller)" in a for a in acts), acts
        acts = W.check(s, rows, NOW + 120, 9999)                        # buyer silent, but a restart 2 min ago
        assert "kit restart pending" in acts, acts
        assert "keepalive missing" in W.check({}, rows[1:], NOW, 10)


def test_harness_streak():
    import harness
    sent = []
    with mock.patch.object(alerts, "send", lambda lvl, key, *a, **k: sent.append((lvl, key))), \
            mock.patch.object(harness, "FAIL_LOG", tmp_json({}, "hf") + ".jsonl"):
        harness._ok()
        for _ in range(10):
            harness._failed("limit", 1, "", "usage limit")
        assert all(l == "info" for l, _ in sent)
        harness._failed("limit", 1, "", "usage limit")                 # the 11th in a row
        assert sent[-1][0] == "urgent" and sent[-1][1].startswith("harness_fail_streak")
        harness._ok()
        harness._failed("limit", 1, "", "x")
        assert sent[-1][0] == "info"


if __name__ == "__main__":
    test_held()
    test_watchdog()
    test_harness_streak()
    print("ok")
