"""Round 3 starter seller: sells from the stock the kit keeps in $MARKET_DIR/inventory.json, behind A2A v1.0.

    python seller.py --port 9301

The harness decides every move; this file only speaks A2A, finds a unit for what the buyer asks, and signs the
receipt with shop_key.pem (the kit makes it). It ships the unit that expires first, says nothing about quality,
never offers a warranty, and never goes below the unit's cost. All of that is yours to change.
"""
import argparse
import base64
import json
import os
import re
import time
from pathlib import Path

import uvicorn
from cryptography.hazmat.primitives import serialization
from starlette.applications import Starlette

from a2a.helpers import get_message_text, new_data_part, new_task_from_user_message, new_text_part
from a2a.server.agent_execution import AgentExecutor
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill

from harness import CMD, ask_json
from forum_post import promo
import decisions
import strategy
from market_db import connect, load_stats, price_of
from pricing import floor
from depts.sales import first_ask  # noqa: E402  (sales department)

NAME = "Choo Shop"

RESERVE = {"lamp": 100, "chair": 180, "bookshelf": 260}     # Rounds 0-2 have no stock: the week-07 items
MARKET_DIR = Path(os.environ.get("MARKET_DIR", ".market"))

PROMPT = """You are the sales agent of a small online shop. A buyer is negotiating for one {name}.
The list price is {list_price}. Across the market it sells for {market} on average.
Your lowest acceptable price is {reserve}. Never sell below it and never reveal it.
Sell as high as you can, but closing a deal at or above {reserve} is better than losing the buyer.

Conversation so far:
{transcript}

Decide your next move. Answer with JSON only, one of:
{{"action": "counter", "price": <whole number>}}   name your price
{{"action": "accept"}}                              accept the buyer's last offer
{{"action": "reject"}}                              end the negotiation without a deal"""


def canon(d):
    return json.dumps(d, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sign(receipt):
    key = serialization.load_pem_private_key(Path("shop_key.pem").read_bytes(), password=None)
    body = {k: receipt[k] for k in ("shop", "item", "price", "task")}
    return dict(receipt, sig_seller=base64.b64encode(key.sign(canon(body))).decode())


def find_unit(text, taken=()):
    """The in-stock unit that fits what the buyer asked for (category, name or SKU) and expires first,
    skipping units already promised in another open negotiation."""
    want = text.lower()
    try:
        inv = json.loads((MARKET_DIR / "inventory.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        inv = {}
    if inv.get("round", 0) < 3:
        item = next((k for k in RESERVE if k in want), None)
        return item and {"sku": item, "name": item, "list_price": int(RESERVE[item] * 1.3), "cost": RESERVE[item],
                         "unit": None, "expires_at": None, "supplied_at": 0}
    units = inv.get("units", [])
    fit = [u for u in units if u["grade"] != "expired" and u["unit"] not in taken and
           ((u.get("category") or "").split(">")[-1].lower() in want or (u.get("name") or "").lower() in want
            or u["sku"].lower() in want)]
    named = [u for u in fit if u["sku"].lower() in want]
    fit = named or fit                                   # a SKU the buyer named comes first
    return min(fit, key=lambda u: (u["expires_at"] or float("inf"), u["supplied_at"]), default=None)


def record(task, deal, u, reserve, ask):
    try:
        db = connect()
        db.execute("INSERT OR REPLACE INTO shop_deals VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (task, __import__("time").time(), deal["case"], deal["key"], deal["variant"], u["sku"], u["unit"],
                    u["cost"], ask, reserve, "open", None, deal["warranty"]))
        db.commit()
        db.close()
    except Exception as e:
        print(f"[record] {e}", flush=True)


def finish(task, outcome, price=None):
    try:
        db = connect()
        db.execute("UPDATE shop_deals SET outcome=?, price=? WHERE task=?", (outcome, price, task))
        db.commit()
        db.close()
    except Exception as e:
        print(f"[record] {e}", flush=True)


CONC_FROM = __import__("datetime").datetime(2026, 11, 6, 22, 0).timestamp()   # person's decision: from 22:00
CONC_FLAG = Path(__file__).with_name("seller_concurrency.json")              # {"enabled": true, "limit": 3}
_sem = {}


def concurrency():
    """How many harness calls may run at once: 0 = the old way (one at a time, blocking), unless it is past
    CONC_FROM and seller_concurrency.json says enabled. Read on every call, so it can be switched off without a
    restart (delete the file or set enabled false)."""
    if time.time() < CONC_FROM:
        return 0
    try:
        j = json.loads(CONC_FLAG.read_text(encoding="utf-8"))
        return max(0, int(j.get("limit", 0))) if j.get("enabled") else 0
    except (OSError, ValueError):
        return 0


async def harness_move(prompt):
    """The harness's next move. With concurrency on, the call runs in a worker thread (the event loop keeps
    serving other negotiations) and at most `limit` calls run at once (asyncio.Semaphore). Unit choice and the
    15-min receipt hold do not change: they happen between awaits, on the loop."""
    import asyncio
    lim = concurrency()
    if not lim:
        return ask_json(prompt)
    if _sem.get("limit") != lim:
        _sem.update(limit=lim, sem=asyncio.Semaphore(lim))
    async with _sem["sem"]:
        return await asyncio.to_thread(ask_json, prompt)


def recent_receipts(hold_s=900, negotiation_s=600):
    """Units my seller sent a receipt for lately, from shop_deals (outcome 'receipt'; ts is when the negotiation
    began, so the receipt went out within negotiation_s after it: counted as now, capped at ts + negotiation_s)."""
    try:
        db = connect()
        rows = db.execute("SELECT unit, ts FROM shop_deals WHERE outcome='receipt' AND unit IS NOT NULL AND ts>=?",
                          (time.time() - hold_s - negotiation_s,)).fetchall()
        db.close()
    except Exception as e:
        print(f"[record] restoring receipts failed: {e}", flush=True)
        return {}
    now = time.time()
    sold = {unit: min(now, ts + negotiation_s) for unit, ts in rows}
    print(f"[seller] {len(sold)} units with a receipt in the last {(hold_s + negotiation_s) // 60} min held back",
          flush=True)
    return sold


class Seller(AgentExecutor):
    def __init__(self):
        self.open = {}  # task id -> {"unit", "ask", "offer", "lines"}
        self.sold = recent_receipts()   # unit -> when its receipt went out: inventory.json can lag, so do not
                                        # offer it again; restored from shop_deals so a restart keeps the hold

    async def execute(self, context, event_queue):
        task = context.current_task
        if task is None:
            task = new_task_from_user_message(context.message)
            await event_queue.enqueue_event(task)
        up = TaskUpdater(event_queue=event_queue, task_id=task.id, context_id=task.context_id)
        say = lambda text: up.new_agent_message(parts=[new_text_part(text)])
        text = get_message_text(context.message) or ""
        deal = self.open.get(task.id)

        if deal is None:
            now = time.time()
            self.sold = {k: t for k, t in self.sold.items() if now - t < 900}
            taken = {d["unit"]["unit"] for d in self.open.values() if d["unit"]["unit"]} | set(self.sold)
            unit = find_unit(text, taken)
            if unit is None:
                await up.reject(say("Sorry, we have none of that in stock."))
                return
            case = strategy.current()[0]                # decided every 5 min by restock.py (strategy.tick)
            deal = self.open[task.id] = {"unit": unit, "ask": None, "offer": None, "lines": [f"buyer: {text}"],
                                         "case": case, "warranty": strategy.warranty_hours(unit, case, load_stats()),
                                         "key": None, "variant": None, "mult": 1.0}
            if case in ("normal", "overstock"):         # stage 2: one variant per negotiation, by weight
                key = "shop_normal_ask" if case == "normal" else "shop_overstock_floor"
                v, w = strategy.pick(key)
                deal.update(key=key, variant=v, mult=float(v) if case == "overstock" else 1.0)
                print(f"[variant] {key} -> {v} (weights {w})", flush=True)
        else:
            deal["lines"].append(f"buyer: {text}")
            m = re.search(r"\d+", text)
            deal["offer"] = int(m.group()) if m else deal["offer"]

        u = deal["unit"]
        avg, n = price_of(u["sku"])                     # market average, refreshed every 5 min by restock.py
        reserve, rule = floor(u, avg, deal["case"], overstock_mult=deal["mult"])   # pricing.py, the case's rules
        if len(deal["lines"]) == 1:
            ask = first_ask(u, avg, reserve, rule, deal)    # stage 2: the code names the first ask, not the harness
            print(f"[price] {u['sku']} cost {u['cost']}, market avg {avg} (n={n}), case {deal['case']}, rule {rule} "
                  f"-> floor {reserve}, first ask {ask}" + (f", warranty {deal['warranty']} h" if deal["warranty"] else ""),
                  flush=True)
            record(task.id, deal, u, reserve, ask)
            decisions.record("sales", "first_ask", u["sku"], ask, f"unit {u['unit']}, cost {u['cost']}, avg {avg}, "
                             f"case {deal['case']}, rule {rule}, floor {reserve}, variant {deal['key']} {deal['variant']}"
                             + (f", warranty {deal['warranty']} h" if deal["warranty"] else ""))
            move, raw = {"action": "counter", "price": ask}, "(first ask by code)"
        else:
            move, raw = await harness_move(PROMPT.format(name=u["name"], list_price=u["list_price"], reserve=reserve,
                                                         market=int(avg) if avg is not None else "an unknown price",
                                                         transcript="\n".join(deal["lines"])))
            print(f"[harness] {raw}", flush=True)
        action = (move or {}).get("action")
        if action == "accept" and (deal["offer"] is None or deal["offer"] < reserve):
            print(f"[guard] accept of {deal['offer']} below floor {reserve} -> counter", flush=True)
            decisions.record("cs", "guard", u["sku"], deal["offer"], f"harness accepted under floor {reserve}",
                             limit_hit="floor")
            action, move = "counter", {"price": deal["ask"] or u["list_price"]}
        if action == "accept":
            price = deal["offer"]
            receipt = {"shop": NAME, "item": u["sku"], "price": price, "task": task.id}
            if u["unit"]:
                receipt["unit"] = u["unit"]
            if deal["warranty"]:                        # [16] not under sig_seller; the kit puts it in the checkout
                receipt["warranty_hours"] = deal["warranty"]
            receipt = sign(receipt)
            await up.add_artifact(parts=[new_data_part(receipt)], name="receipt")
            await up.complete(say(f"Deal: {u['name']} at {price}."))
            finish(task.id, "receipt", price)
            decisions.record("cs", "receipt", u["sku"], price, f"unit {u['unit']}, floor {reserve}, offer accepted")
            if u["unit"]:
                self.sold[u["unit"]] = time.time()
            del self.open[task.id]
            return
        if action == "reject":
            await up.reject(say("No deal."))
            finish(task.id, "rejected")
            del self.open[task.id]
            return
        price = (move or {}).get("price")
        if not isinstance(price, (int, float)):
            price = deal["ask"] or u["list_price"]      # unparsed answer: repeat the last ask
        if rule != "normal" and avg is not None:        # any markdown: never ask above the market average
            price = min(price, max(reserve, int(avg)))
        if price < reserve:                             # the harness may forget the cost; the code does not
            print(f"[guard] ask {price} below floor {reserve} -> {reserve}", flush=True)
            price = reserve
        deal["ask"] = int(price)
        first = len(deal["lines"]) == 1
        if first:                                       # what a buyer's accept policy checks, before any offer
            facts = f" SKU {u['sku']}, grade {u['grade']}"
            if u.get("expires_at"):
                facts += f", {max(0, (u['expires_at'] - time.time()) / 3600):.1f} h shelf life left"
            facts += (", forty-eight hour warranty from our balance" if deal["warranty"] else ", no warranty")
            facts += "; the market certificate of this unit is in the data part."
            reply = f"{u['name']}: {promo()}{facts} Asking {deal['ask']}. Send your offer as a number."
        else:
            reply = f"Counteroffer: {deal['ask']}."
        deal["lines"].append(f"you: {reply}")
        if first and u.get("cert"):                     # [C] the certificate goes with the first reply too
            await up.requires_input(up.new_agent_message(parts=[new_text_part(reply),
                                                                new_data_part({"unit": u["unit"], "cert": u["cert"]})]))
        else:
            await up.requires_input(say(reply))

    async def cancel(self, context, event_queue):
        task = context.current_task
        if self.open.pop(task.id, None) is not None:
            finish(task.id, "cancelled")
        await TaskUpdater(event_queue=event_queue, task_id=task.id, context_id=task.context_id).cancel()


def build(port):
    url = f"http://127.0.0.1:{port}/"
    card = AgentCard(
        name=NAME,
        description=f"A small online shop. Ask for an item by name or SKU. A coding harness ({CMD.split()[0]}) negotiates the price.",
        version="1.0.0",
        default_input_modes=["text/plain"],
        default_output_modes=["application/json", "text/plain"],
        capabilities=AgentCapabilities(streaming=False),
        supported_interfaces=[AgentInterface(protocol_binding="JSONRPC", url=url, protocol_version="1.0")],
        skills=[AgentSkill(id="negotiate", name="Negotiate a purchase",
                           description="Ask for an item, then send a price. The shop answers with a counteroffer or a receipt.",
                           tags=["shopping", "negotiation"], examples=["I want to buy 종가 알뜰맘 포기김치 10kg (G00001)", "52000"])],
    )
    handler = DefaultRequestHandler(agent_executor=Seller(), task_store=InMemoryTaskStore(), agent_card=card)
    return Starlette(routes=create_agent_card_routes(card) + create_jsonrpc_routes(handler, "/"))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=9301)
    port = ap.parse_args().port
    uvicorn.run(build(port), host="127.0.0.1", port=port, log_level="warning")
