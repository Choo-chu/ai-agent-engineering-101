"""Strategy analyst, step 3: what an approval does, and how to undo it.

policy keys      policy.json via policy.write(by="analyst+person"); the previous value is kept for undo.
                 purchasing.sofa_trial_extend_h moves sofa_trial_end later by that many hours.
limits keys      STOCK_CAP (with STOCK_EXIT = 88%), HIGH_MAX (depts/qc.py), CASH_RESERVE, only inside
                 limits.ANALYST_MAX (checked again here; the maxima are code, nobody changes them from here):
                   1. b0 baseline run with the current code
                   2. the file is rewritten (temp file + replace) and the change is recorded (*_CHANGES)
                   3. b0 baseline run again: any change in a unit's floor / first ask / warranty or in the decided
                      shop case -> the files are restored, an alert goes out, the approval fails
                   4. otherwise the changed files alone are committed and pushed
undo             every applied approval stores what it replaced; the result message carries a 되돌리기 button
                 (revert:<id>), which applies the old value the same way (limits again through the b0 check).
"""
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime

import alerts
import decisions
from depts import analyst

HERE = analyst.HERE
PY = sys.executable
GIT_ATTR = "\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"


def _write(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    os.replace(tmp, path)


def _read(path):
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


# ---------------------------------------------------------------- policy keys
def apply_policy(key, value, pid):
    import policy
    sec, k = key.split(".", 1)
    if k == "sofa_trial_extend_h":
        end = policy.get("purchasing", "sofa_trial_end")
        start = policy.get("purchasing", "sofa_trial_start")
        new_end = max(end, time.time()) + float(value) * 3600
        new = policy.write({"purchasing": {"sofa_trial_end": round(new_end), "sofa_trial_start": start or round(time.time())}},
                           f"analyst #{pid} approved: sofa trial +{value} h", by="analyst+person")
        return {"undo": {"purchasing.sofa_trial_end": end}, "text": f"소파 시험 종료 {datetime.fromtimestamp(new_end):%m-%d %H:%M}, policy v{new['version']}"}
    old = (policy.load().get(sec) or {}).get(k)
    if old is None and k in ("high_share", "high_max"):
        old = None                                        # was the policy table's value: undo removes the key
    new = policy.write({sec: {k: value}}, f"analyst #{pid} approved: {key} -> {value}", by="analyst+person")
    return {"undo": {key: old}, "text": f"{key} {old} -> {value}, policy v{new['version']}"}


def undo_policy(undo, pid):
    import policy
    cur = policy.load()
    sections = {}
    for full, old in undo.items():
        sec, k = full.split(".", 1)
        sections.setdefault(sec, {})[k] = old
    new = {s: dict(cur.get(s) or {}) for s in policy.DEFAULTS}
    for sec, kv in sections.items():
        for k, old in kv.items():
            if old is None:
                new[sec].pop(k, None)
            else:
                new[sec][k] = old
    v = policy.write({s: new[s] for s in sections}, f"analyst #{pid} reverted by the person", by="person",
                     replace=True)
    return f"되돌림: {undo}, policy v{v['version']}"


# ---------------------------------------------------------------- limits keys
LIMIT_FILES = {"limits.STOCK_CAP": "limits.py", "limits.CASH_RESERVE": "limits.py", "limits.HIGH_MAX": os.path.join("depts", "qc.py")}


def current_limit(key):
    import importlib
    import limits
    importlib.reload(limits)
    if key == "limits.HIGH_MAX":
        m = re.search(r"^HIGH_MAX = ([\d_]+)", _read(os.path.join(HERE, "depts", "qc.py")), re.M)
        return int(m.group(1).replace("_", ""))
    return {"limits.STOCK_CAP": limits.STOCK_CAP, "limits.CASH_RESERVE": limits.CASH_RESERVE}[key]


def check_max(key, value):
    import limits
    mx = limits.ANALYST_MAX
    ok = {"limits.STOCK_CAP": 1_000_000 <= value <= mx["STOCK_CAP"],
          "limits.HIGH_MAX": 100_000 <= value <= mx["HIGH_MAX"],
          "limits.CASH_RESERVE": mx["CASH_RESERVE_MIN"] <= value <= 5_000_000}[key]
    if not ok:
        raise ValueError(f"{key}={value} is outside the fixed maxima {mx}")


def edit_limit(key, value, pid, now):
    """Rewrite the one constant (and STOCK_EXIT with STOCK_CAP) and record the change. Returns {path: old text}."""
    v = int(value)
    stamp = f"{datetime.fromtimestamp(now):%m/%d %H:%M}"
    path = os.path.join(HERE, LIMIT_FILES[key])
    old = {path: _read(path)}
    text = old[path]
    if key == "limits.STOCK_CAP":
        text, n = re.subn(r"^STOCK_CAP = [\d_]+", f"STOCK_CAP = {v:_}", text, flags=re.M)
        exit_ = round(v * 0.88 / 10_000) * 10_000
        text, n2 = re.subn(r"^STOCK_EXIT = [\d_]+", f"STOCK_EXIT = {exit_:_}", text, flags=re.M)
        assert n == 1 and n2 == 1
        text += f"STOCK_CAP_CHANGES.append(({now:.0f}, {v:_}))   # {stamp} analyst #{pid}, approved\n"
    elif key == "limits.CASH_RESERVE":
        text, n = re.subn(r"^CASH_RESERVE = [\d_]+", f"CASH_RESERVE = {v:_}", text, flags=re.M)
        assert n == 1
        text += f"CASH_RESERVE_CHANGES.append(({now:.0f}, {v:_}))   # {stamp} analyst #{pid}, approved\n"
    else:
        text, n = re.subn(r"^HIGH_MAX = [\d_]+", f"HIGH_MAX = {v:_}", text, flags=re.M)
        assert n == 1
        lpath = os.path.join(HERE, "limits.py")
        old[lpath] = _read(lpath)
        _write(lpath, old[lpath] + f"HIGH_MAX_CHANGES.append(({now:.0f}, {v:_}))   # {stamp} analyst #{pid}, approved\n")
    _write(path, text)
    return old


def baseline(label):
    r = subprocess.run([PY, "-X", "utf8", os.path.join("tools", "baseline.py"), "run", "b0", label], cwd=HERE,
                       capture_output=True, text=True, encoding="utf-8", timeout=300,
                       env=dict(os.environ, PYTHONUTF8="1"))
    if r.returncode:
        raise RuntimeError(f"baseline run failed: {(r.stderr or r.stdout)[-200:]}")
    with open(os.path.join(HERE, "reports", "cache", "baseline", "b0", f"out_{label}.json"), encoding="utf-8") as f:
        return json.load(f)


def anomalies(a, b):
    """Differences that must not happen for a limit change: per-unit floors / asks / warranty, the decided case."""
    bad = []
    for u in sorted(set(a["units"]) | set(b["units"])):
        if a["units"].get(u) != b["units"].get(u):
            bad.append(f"unit {u}: {json.dumps(a['units'].get(u))[:80]} -> {json.dumps(b['units'].get(u))[:80]}")
    if a["decide"] != b["decide"]:
        bad.append(f"decided case {a['decide']} -> {b['decide']}")
    return bad


def git_commit(paths, msg):
    rel = [os.path.relpath(p, HERE) for p in paths]
    r = subprocess.run(["git", "commit", "-q", "-m", msg + GIT_ATTR, "--", *rel], cwd=HERE, capture_output=True,
                       text=True, timeout=120)
    if r.returncode:
        raise RuntimeError(f"git commit failed: {r.stderr.strip()[:150]}")
    p = subprocess.run(["git", "push", "-q", "origin", "week-08"], cwd=HERE, capture_output=True, text=True, timeout=120)
    head = subprocess.run(["git", "log", "--oneline", "-1"], cwd=HERE, capture_output=True, text=True).stdout.strip()
    return head[:7] + ("" if p.returncode == 0 else " (push failed)")


def apply_limit(key, value, pid, why="approved"):
    value = int(value)
    check_max(key, value)
    old_value = current_limit(key)
    now = time.time()
    tag = f"an{pid}_{int(now)}"
    pre = baseline(tag + "_pre")
    old = edit_limit(key, value, pid, now)
    try:
        post = baseline(tag + "_post")
        bad = anomalies(pre, post)
    except Exception as e:
        bad = [f"baseline failed: {type(e).__name__}: {str(e)[:120]}"]
    if bad:
        for path, text in old.items():                 # restore exactly what was there
            _write(path, text)
        decisions.record("analyst", "apply_cancelled", key, value, f"#{pid}: b0 check: {bad[:3]}")
        alerts.send("urgent", f"analyst_cancel:{pid}", f"승인 #{pid} {key} -> {value:,} 취소: b0 비교 이상 {bad[:2]}")
        raise RuntimeError(f"b0 check failed, nothing changed: {bad[:2]}")
    diff_buy = (pre["buy"]["real"]["budget"], post["buy"]["real"]["budget"], len(post["buy"]["real"]["plan"]))
    head = git_commit(list(old), f"week-08: analyst #{pid} {why}: {key} {old_value:,} -> {value:,} (b0: floors, first asks, "
                                 f"case unchanged; real budget {diff_buy[0]:,} -> {diff_buy[1]:,})")
    return {"undo": {key: old_value},
            "text": f"{key} {old_value:,} -> {value:,}; b0 이상 없음 (예산 {diff_buy[0]:,} -> {diff_buy[1]:,}); 커밋 {head}"}


# ---------------------------------------------------------------- handlers registered with depts/analyst.py
def _store(pid, res):
    d = analyst.db()
    try:
        cols = [r[1] for r in d.execute("PRAGMA table_info(proposals)")]
        if "undo" not in cols:
            d.execute("ALTER TABLE proposals ADD COLUMN undo TEXT")
        d.execute("UPDATE proposals SET undo=? WHERE id=?", (json.dumps(res["undo"]), pid))
        d.commit()
    finally:
        d.close()


def handle_policy(p):
    res = apply_policy(p["key"], json.loads(p["value"]), p["id"])
    _store(p["id"], res)
    return res["text"]


def handle_limit(p):
    res = apply_limit(p["key"], json.loads(p["value"]), p["id"])
    _store(p["id"], res)
    return res["text"]


def revert(p):
    """Undo an applied approval (the 되돌리기 button)."""
    undo = json.loads(p.get("undo") or "{}")
    if not undo:
        return "되돌릴 내용 없음"
    out = []
    for key, old in undo.items():
        if key.startswith("limits."):
            out.append(apply_limit(key, old, p["id"], why="reverted by the person")["text"])
        else:
            out.append(undo_policy({key: old}, p["id"]))
    decisions.record("analyst", "reverted", p["key"], undo, f"#{p['id']}")
    return "; ".join(out)


def register():
    analyst.HANDLERS["policy"] = handle_policy
    analyst.HANDLERS["limit"] = handle_limit
    analyst.REVERT = revert
    analyst.REAPPLY = reapply


# ---------------------------------------------------------------- step 4: checks after an approval
CHECK_H = 3                  # person's decision 11/06: 3 h before vs 3 h after an applied approval
CHECK_EVERY_S = 300
REAPPLY_BUTTON = lambda pid: {"inline_keyboard": [[{"text": "다시 적용", "callback_data": f"reapply:{pid}"}]]}


def _cols(d):
    cols = [r[1] for r in d.execute("PRAGMA table_info(proposals)")]
    for c, t in (("undo", "TEXT"), ("checked", "INTEGER")):
        if c not in cols:
            d.execute(f"ALTER TABLE proposals ADD COLUMN {c} {t}")


def _approved(d):
    d.row_factory = __import__("sqlite3").Row
    return [dict(r) for r in d.execute("SELECT * FROM proposals WHERE status='approved' AND kind IN ('policy','limit')")]


def _auto_revert(p, why):
    """Revert an approval on its own (check or CEO guard), mark it, and offer 다시 적용 (11/07: as a policy change
    message with [되돌리기] = 다시 적용 and [24시간 고정]; a pinned key is not reverted)."""
    from depts import policy_notify
    if policy_notify.pinned(p["key"]):
        decisions.record("analyst", "pinned", p["key"], json.loads(p["value"]), f"#{p['id']}: {why}; pinned by the "
                         "person for 24 h: not reverted")
        analyst.log(f"proposal #{p['id']} not reverted: {p['key']} pinned")
        return
    try:
        text = revert(p)
    except Exception as e:
        alerts.send("urgent", f"analyst_autorevert:{p['id']}", f"승인 #{p['id']} 자동 되돌리기 실패: {type(e).__name__}: {str(e)[:120]}")
        return
    d = analyst.db()
    try:
        d.execute("UPDATE proposals SET status='auto_reverted', result=? WHERE id=?", (f"{why} | {text}"[:500], p["id"]))
        d.commit()
    finally:
        d.close()
    decisions.record("analyst", "auto_reverted", p["key"], json.loads(p["value"]), f"#{p['id']}: {why}")
    undo = json.loads(p.get("undo") or "{}")
    policy_notify.notify("analyst", [{"key": p["key"], "old": json.loads(p["value"]), "new": undo.get(p["key"]),
                                      "where": (f"limits.py > {p['key'].split('.', 1)[1]}" if p["key"].startswith("limits.")
                                                else f"policy.json > {p['key']}")}],
                         f"승인 #{p['id']} 반영 후 {CHECK_H}시간 점검: {why}", evidence=text[:300],
                         version=("승인 값", "되돌린 값"), next_at="없음 ([되돌리기] = 다시 적용)",
                         extra={"pid": p["id"]}, log=analyst.log)
    analyst.log(f"proposal #{p['id']} auto-reverted: {why}")


def reapply(p):
    """The 다시 적용 button: apply the approved value again (limits through the b0 check again)."""
    res = (apply_limit(p["key"], json.loads(p["value"]), p["id"], why="re-applied by the person")
           if p["kind"] == "limit" else apply_policy(p["key"], json.loads(p["value"]), p["id"]))
    d = analyst.db()
    try:
        _cols(d)
        d.execute("UPDATE proposals SET status='approved', decided_ts=?, checked=0, undo=? WHERE id=?",
                  (time.time(), json.dumps(res["undo"]), p["id"]))
        d.commit()
    finally:
        d.close()
    decisions.record("analyst", "reapplied", p["key"], json.loads(p["value"]), f"#{p['id']}")
    return res["text"]


def check_approvals(now=None):
    """Every CHECK_EVERY_S, in the analyst process (it may run b0 and git, which the restock hook must not wait for):
    1. the CEO guard reverted (logs/ceo_revert.json is new): revert every applied approval, offer 다시 적용
    2. each approval CHECK_H after it was applied: the CHECK_H before vs after (dept_reports.window, sofa trial
       units left out once the trial stopped); clearly worse (ceo_policy.worse) -> revert it, offer 다시 적용."""
    import dept_reports
    from depts import ceo_policy
    now = now or time.time()
    if now - float(analyst_meta("approvals_ts", 0)) < CHECK_EVERY_S:
        return
    analyst_set("approvals_ts", now)
    d = analyst.db()
    try:
        _cols(d)
        d.commit()
        live = _approved(d)
    finally:
        d.close()
    try:
        flag = json.load(open(os.path.join(HERE, "logs", "ceo_revert.json"), encoding="utf-8"))
    except (OSError, ValueError):
        flag = None
    if flag and flag["ts"] > float(analyst_meta("ceo_revert_seen", 0)):
        analyst_set("ceo_revert_seen", flag["ts"])
        for p in live:
            if (p["decided_ts"] or 0) <= flag["ts"]:
                _auto_revert(p, f"CEO 가드 되돌리기 ({'; '.join(flag['why'])[:150]})")
        return
    cat = ceo_policy._catalog()
    for p in live:
        t = p["decided_ts"] or 0
        if p.get("checked") or now < t + CHECK_H * 3600:
            continue
        d = analyst.db()
        try:
            ex = ceo_policy.trial_units_if_stopped(d, now)
            before = dept_reports.window(d, t - CHECK_H * 3600, t, cat, ex)
            after = dept_reports.window(d, t, t + CHECK_H * 3600, cat, ex)
            d.execute("UPDATE proposals SET checked=1 WHERE id=?", (p["id"],))
            d.commit()
        finally:
            d.close()
        # person's decision 11/07 ~14:50: a limits key (STOCK_CAP, HIGH_MAX, CASH_RESERVE) is a shop key, so buyer
        # Saved is not a condition for it (buyer experiments run); other keys (buyer keys included) keep it
        buyer = not p["key"].startswith("limits.")
        bad = ceo_policy.worse(after, before, min_sales=10, min_accounts=5, min_paid=5, buyer=buyer)
        summary = {k: [after[k], before[k]] for k in ("sales", "revenue", "profit", "stars", "buyer_paid",
                                                       "buyer_saved_sum")}   # revenue: 11/07 ~17:55
        if not buyer:
            summary["buyer_saved"] = "information only (limits key)"
        decisions.record("analyst", "approval_check", p["key"], summary, f"#{p['id']}: " + ("; ".join(bad) or "not worse"))
        if bad:
            _auto_revert(p, f"반영 전후 {CHECK_H}시간 비교에서 나빠짐: {'; '.join(bad)}")
        else:
            analyst.log(f"proposal #{p['id']} check ok (3 h after vs before): {summary}")


def analyst_meta(k, default=None):
    d = analyst.db()
    try:
        r = d.execute("SELECT v FROM analyst_meta WHERE k=?", (k,)).fetchone()
        return r[0] if r else default
    finally:
        d.close()


def analyst_set(k, v):
    d = analyst.db()
    try:
        d.execute("INSERT OR REPLACE INTO analyst_meta VALUES (?,?)", (k, str(v)))
        d.commit()
    finally:
        d.close()
