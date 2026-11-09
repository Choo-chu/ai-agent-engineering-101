"""Keep tests off the live config and log files (11/09 ~19:30): every helper here points a module's path at a new
temp file, so a test never reads open_expiry.json, policy.json, soft_neg.json ... nor writes logs/*.
    from _isolate import tmp_json, tmp_path, policy
"""
import json
import os
import tempfile

_DIR = tempfile.mkdtemp(prefix="w08-test-")


def tmp_path(name):
    """A path in this run's temp dir (the file is not created)."""
    return os.path.join(_DIR, name)


def tmp_json(obj, name=None):
    """A temp file holding obj as JSON; returns its path."""
    fd, p = tempfile.mkstemp(suffix=".json", dir=_DIR, prefix=(name or "rules") + "-")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    return p


def policy(data=None):
    """policy.py reads a temp policy.json ({} = the code's DEFAULTS) and writes its history to a temp file."""
    import policy as P
    P.PATH = tmp_json(data or {}, "policy")
    P.HISTORY = tmp_path("policy_history.jsonl")
    P._cache.update(mtime=None, data=None, clipped=set())
    return P
