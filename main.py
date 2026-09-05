"""Team: Fozza · Product: MicroLC — API server (FastAPI, port 8000).

    POST /api/deal/create                      {preset, lc_amount}      -> new deal with fixture documents
    POST /api/deal/{id}/documents              multipart PDFs           -> replace documents
    POST /api/deal/{id}/examine?parser=auto    examiner (Groq or template) -> discrepancies, k
    POST /api/deal/{id}/lock                   lock 101% in 7 RLUSD escrows (background, Tickets)
    GET  /api/deal/{id}/negotiate/stream?mode=live|mock   SSE: agent | update | settlement | done
    POST /api/deal/{id}/settle {m}             settle manually with an integer m
    POST /api/deal/{id}/sweep                  return expired tranches to the buyer
    GET  /api/deal/{id} · /api/deal/{id}/documents/{name} · /api/feed · /api/env · /api/deals

State lives in state/deals/{id}/state.json (gitignored). Wallet custody is a demo simplification:
the server signs for buyer and platform from state/wallets.json.
"""
from __future__ import annotations

import json
import os
import secrets
import shutil
import threading
import time
from datetime import date
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

load_dotenv()

from doc_generator import DOC_FILES, PRESETS, build_presentation, generate_set  # noqa: E402
from examiner import RULES, TemplateParser, examine, get_parser  # noqa: E402
from negotiator_graph import AgentOffer, ScriptedAgent, build_graph, initial_state, stream  # noqa: E402
from settlement_engine import (REFUSED_M, Deal, InsufficientFunds, SettlementEngine, fmt, money,  # noqa: E402
                               normalize_m, payout_for, payout_table, total_locked)
from ucp_articles import ARTICLES  # noqa: E402
from verifier_agent import BudgetGuard, OracleClient, make_verifier  # noqa: E402
from xrpl_escrow import EXPLORER_ACCOUNT, EXPLORER_TX, LedgerClient, load_wallets, ripple_now, wallets_available  # noqa: E402

from scripts.topup_buyer import top_up  # noqa: E402

STATE = Path("state")
DEALS = STATE / "deals"
EXPIRY = int(os.getenv("ESCROW_EXPIRY_SECONDS", "180"))
DEMO_TOPUP_TARGET = 200_000  # RLUSD the demo buyer is refilled to when DEMO_AUTO_TOPUP is on


def _demo_auto_topup() -> bool:
    return os.getenv("DEMO_AUTO_TOPUP", "").strip().lower() in ("1", "true", "yes", "on")
app = FastAPI(title="MicroLC API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
_lock = threading.Lock()


# --------------------------------------------------------------------------- wallets / ledger
def _wallets() -> Optional[dict]:
    p = STATE / "wallets.json"
    return load_wallets(str(p)) if wallets_available(str(p)) else None


def _ledger() -> LedgerClient:
    w = _wallets()
    return LedgerClient(w["rpc_url"] if w else os.getenv("XRPL_RPC_URL"))


# --------------------------------------------------------------------------- persistence
def _dir(deal_id: str) -> Path:
    d = DEALS / deal_id
    if not d.exists():
        raise HTTPException(404, f"deal {deal_id} not found")
    return d


def load_state(deal_id: str) -> dict:
    return json.loads((_dir(deal_id) / "state.json").read_text())


def save_state(deal_id: str, st: dict) -> None:
    with _lock:
        (DEALS / deal_id / "state.json").write_text(json.dumps(st, indent=2, default=str))


def public_view(st: dict) -> dict:
    out = json.loads(json.dumps(st, default=str))
    esc = out.get("escrow")
    if esc:
        for t in esc.get("tranches", []):
            t.pop("fulfillment", None)
    return out


def feed_add(st: dict, label: str, tx_hash: Optional[str], result: str = "tesSUCCESS", extra: Optional[dict] = None) -> dict:
    item = {"ts_ms": int(time.time() * 1000), "label": label, "hash": tx_hash, "result": result,
            "explorer": EXPLORER_TX.format(tx_hash) if tx_hash else None, **(extra or {})}
    st.setdefault("ledger_feed", []).append(item)
    return item


# --------------------------------------------------------------------------- models
class CreateReq(BaseModel):
    preset: str = "discrepant"
    lc_amount: Optional[str] = None


class SettleReq(BaseModel):
    m: Optional[int] = None


# --------------------------------------------------------------------------- endpoints
@app.get("/api/env")
def env():
    w = _wallets()
    addrs = {k: {"address": v["address"], "explorer": EXPLORER_ACCOUNT.format(v["address"])} for k, v in (w or {}).get("wallets", {}).items()}
    return {"network": os.getenv("XRPL_NETWORK", "xrpl:1"), "explorer_tx": EXPLORER_TX, "wallets": addrs,
            "presets": list(PRESETS), "rules": {r: {"code": c, "article": a, "severity": s, "checkable": k} for r, (c, a, s, k) in RULES.items()},
            "articles": ARTICLES, "payout_table": payout_table(10000), "expiry_seconds": EXPIRY,
            "groq": bool(os.getenv("GROQ_API_KEY")), "oracle_url": os.getenv("ORACLE_URL", "http://127.0.0.1:8001"),
            "models": {"small": os.getenv("GROQ_SMALL_MODEL"), "large": os.getenv("GROQ_LARGE_MODEL")}}


@app.get("/api/deals")
def list_deals():
    DEALS.mkdir(parents=True, exist_ok=True)
    out = []
    for d in sorted(DEALS.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if (d / "state.json").exists():
            st = json.loads((d / "state.json").read_text())
            out.append({"deal_id": st["deal_id"], "preset": st.get("preset"), "status": st.get("status"), "k": (st.get("examination") or {}).get("k")})
    return out


@app.post("/api/deal/create")
def create(req: CreateReq):
    if req.preset not in PRESETS:
        raise HTTPException(400, f"preset must be one of {PRESETS}")
    deal_id = f"{req.preset[:4]}-{int(time.time()) % 100000:05d}{secrets.token_hex(1)}"  # unique even within one second
    d = DEALS / deal_id
    d.mkdir(parents=True, exist_ok=True)
    generate_set(req.preset, d.parent / "_gen")
    for f in (d.parent / "_gen" / req.preset).iterdir():
        shutil.copy(f, d / f.name)
    pres = build_presentation(req.preset)
    lc = pres["deal"]
    if req.lc_amount:
        lc["amount"] = float(req.lc_amount)
    (d / "deal.json").write_text(json.dumps(lc, indent=2))
    w = _wallets()
    st = {
        "deal_id": deal_id, "preset": req.preset, "status": "CREATED", "created_ms": int(time.time() * 1000),
        "lc": lc, "documents": list(DOC_FILES.values()),
        "parties": {k: v["address"] for k, v in (w or {}).get("wallets", {}).items()},
        "examination": None, "escrow": None, "negotiation": None, "settlement": None, "ledger_feed": [],
        "payout_table": payout_table(lc["amount"]),
    }
    save_state(deal_id, st)
    return public_view(st)


@app.get("/api/deal/{deal_id}")
def get_deal(deal_id: str):
    return public_view(load_state(deal_id))


@app.get("/api/deal/{deal_id}/documents/{name}")
def get_document(deal_id: str, name: str):
    p = _dir(deal_id) / name
    if not p.exists() or p.suffix != ".pdf":
        raise HTTPException(404, "document not found")
    return FileResponse(str(p), media_type="application/pdf")


@app.post("/api/deal/{deal_id}/documents")
async def upload_documents(deal_id: str, files: list[UploadFile]):
    d = _dir(deal_id)
    saved = []
    for f in files:
        if f.filename not in DOC_FILES.values():
            raise HTTPException(400, f"unexpected file {f.filename}; expected {list(DOC_FILES.values())}")
        (d / f.filename).write_bytes(await f.read())
        saved.append(f.filename)
    st = load_state(deal_id)
    st["status"], st["examination"] = "DOCUMENTS_UPLOADED", None
    save_state(deal_id, st)
    return {"saved": saved}


@app.post("/api/deal/{deal_id}/examine")
def run_examine(deal_id: str, parser: str = "auto"):
    d = _dir(deal_id)
    st = load_state(deal_id)
    t0 = time.time()
    res = examine(d, get_parser(parser))
    res["elapsed_ms"] = int((time.time() - t0) * 1000)
    st["examination"] = res
    st["status"] = "EXAMINED"
    save_state(deal_id, st)
    return public_view(st)


def _warn(st: dict, code: str, message: str) -> None:
    """Operator-facing warning the console shows as a banner. Never an exception, never a LedgerError string."""
    st.setdefault("warnings", []).append({"ts_ms": int(time.time() * 1000), "code": code, "message": message})


def _insufficient(st: dict, need, have) -> None:
    """Pre-flight failed: stay at EXAMINED with no escrow record so the Lock button re-enables."""
    _warn(st, "INSUFFICIENT_RLUSD", f"Insufficient RLUSD: need {fmt(need)}, have {fmt(have)} — run scripts/topup_buyer.py")
    st["escrow"] = None
    st["status"] = "EXAMINED"


@app.post("/api/deal/{deal_id}/lock")
def lock(deal_id: str, expiry_seconds: Optional[int] = None):
    st = load_state(deal_id)
    if not st.get("examination"):
        raise HTTPException(400, "examine the deal first")
    esc = st.get("escrow")
    if esc and esc.get("status") in ("LOCKING", "LOCKED"):
        return public_view(st)
    w = _wallets()
    if not w:
        raise HTTPException(503, "no wallets; run scripts/bootstrap_wallets.py")
    # pre-flight: read the buyer's spendable RLUSD and refuse to submit a ladder it cannot fund
    ledger = _ledger()
    buyer_addr, issuer_addr = w["wallets"]["buyer"]["address"], w["wallets"]["issuer"]["address"]
    need = money(total_locked(st["lc"]["amount"]))
    have = money(ledger.iou_balance(buyer_addr, issuer_addr))
    if have < need and _demo_auto_topup():
        # testnet demo only: mint the shortfall from our own test issuer so the demo never stalls on funds
        try:
            res = top_up(ledger, w["_wallets"]["issuer"], w["_wallets"]["buyer"], DEMO_TOPUP_TARGET, log=lambda *_: None)
        except Exception as exc:  # fall through to the ordinary warning path
            _warn(st, "DEMO_TOPUP_FAILED", f"Demo top-up failed: {type(exc).__name__}: {exc}")
            res = None
        if res and res["minted"] > 0:
            _warn(st, "INFO", f"Demo top-up: minted {fmt(res['minted'])} RLUSD from test issuer")
            feed_add(st, f"Payment demo top-up {fmt(res['minted'])} RLUSD issuer -> buyer (testnet only)", res["tx_hash"],
                     "tesSUCCESS", {"kind": "topup"})
            have = money(res["balance"])
    if have < need:
        _insufficient(st, need, have)
        save_state(deal_id, st)
        return public_view(st)
    if esc and esc.get("tranches"):
        st.setdefault("lock_attempts", []).append(esc)  # keep the hashes of a failed attempt
    st["escrow"] = {"status": "LOCKING", "tranches": []}
    st["status"] = "LOCKING"
    save_state(deal_id, st)
    threading.Thread(target=_lock_worker, args=(deal_id, expiry_seconds or EXPIRY), daemon=True).start()
    return public_view(st)


def _lock_worker(deal_id: str, expiry: int) -> None:
    st = load_state(deal_id)
    w = _wallets()
    ww = w["_wallets"]
    try:
        eng = SettlementEngine(_ledger(), use_tickets=True)
        deal = None
        t0 = time.time()
        for deal in eng.open_deal(st["lc"]["amount"], ww["buyer"], w["wallets"]["seller"]["address"],
                                  w["wallets"]["platform"]["address"], w["wallets"]["issuer"]["address"], expiry, deal_id):
            pass
        st = load_state(deal_id)
        st["escrow"] = deal.to_dict(public=False)
        st["escrow"]["lock_seconds"] = round(time.time() - t0, 1)
        for t in deal.tranches:
            if t.create_hash:
                feed_add(st, f"EscrowCreate {t.name} {t.amount} RLUSD -> {t.destination}", t.create_hash,
                         t.create_result or ("tesSUCCESS" if t.create_hash else "FAILED"), {"kind": "create", "tranche": t.index})
        if deal.status == "LOCKED":
            if st.get("status") == "LOCKING":  # never clobber a status another request wrote meanwhile
                st["status"] = "LOCKED"
        else:
            landed = [t for t in deal.tranches if t.status in ("RETURNED", "RETURN_PENDING")]
            pending = [t for t in landed if t.status == "RETURN_PENDING"]
            for t in landed:
                if t.action_hash:
                    feed_add(st, f"EscrowCancel {t.name} {t.amount} RLUSD (rollback, returned)", t.action_hash,
                             t.action_result or "", {"kind": "rollback", "tranche": t.index})
            msg = (f"{deal.error}. {len(landed)} escrow(s) landed and were rolled back: "
                   f"{len(landed) - len(pending)} returned now, {len(pending)} return automatically after CancelAfter.")
            _warn(st, "LOCK_FAILED", msg)
            st["escrow"]["error"] = msg
            st["status"] = "LOCK_FAILED"
            if pending:
                _schedule_sweep(deal_id, max(t.cancel_after or 0 for t in pending))
    except InsufficientFunds as exc:
        st = load_state(deal_id)
        _insufficient(st, exc.need, exc.have)
    except Exception as exc:  # surface, never crash the API
        st = load_state(deal_id)
        st["escrow"] = {"status": "FAILED", "error": f"{type(exc).__name__}: {exc}", "tranches": []}
        _warn(st, "LOCK_FAILED", f"Lock failed before any escrow was created: {type(exc).__name__}: {exc}")
        st["status"] = "LOCK_FAILED"
    save_state(deal_id, st)


def _schedule_sweep(deal_id: str, cancel_after: int) -> None:
    """Return RETURN_PENDING tranches to the buyer as soon as the ledger lets anyone cancel them."""
    def run():
        while ripple_now() <= cancel_after + 5:
            time.sleep(5)
        try:
            _do_sweep(deal_id)
        except Exception:  # best effort; the operator can still press Sweep
            pass
    threading.Thread(target=run, daemon=True).start()


# --------------------------------------------------------------------------- negotiation (SSE)
def _sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


MOCK_EVIDENCE = {"rule_id": "R15", "verdict": "CONFIRMS", "provider": "harbor-ais", "price_rlusd": "0.05",
                 "tx_hash": None, "summary": "oracle ATD 2026-08-23 equals the B/L on-board date; shipment was late by evidence"}


def mock_verifier(state):
    """Stage fallback: same event shape as the live verifier, no payment made."""
    chk = [d for d in state["discrepancies"] if d.get("checkable")]
    ts = lambda: int(time.time() * 1000)  # noqa: E731
    if not chk:
        return {"evidence": [], "verifier": {"triggered": False, "reason": "no externally checkable discrepancy", "mock": True},
                "events": [{"ts_ms": ts(), "round": 0, "actor": "verifier", "action": "skip", "rungs": None, "cited": [],
                            "rationale": "no externally checkable discrepancy", "valid": True}]}
    ev = [
        {"ts_ms": ts(), "round": 0, "actor": "verifier", "action": "discover", "rungs": None, "cited": [d["rule_id"] for d in chk],
         "rationale": "2 providers: harbor-ais@0.05 RLUSD/450ms, portlog-premium@0.20 RLUSD/120ms", "valid": True},
        {"ts_ms": ts(), "round": 0, "actor": "verifier", "action": "decide", "rungs": None, "cited": [],
         "rationale": "chose harbor-ais at 0.05 RLUSD: cheapest provider covering the disputed fields", "valid": True},
        {"ts_ms": ts(), "round": 0, "actor": "verifier", "action": "pay", "rungs": None, "cited": [],
         "rationale": "MOCK: x402 payment skipped (live mode pays 0.05 RLUSD on XRPL testnet)", "valid": True},
    ]
    evidence = []
    for d in chk:
        e = dict(MOCK_EVIDENCE, rule_id=d["rule_id"])
        evidence.append(e)
        ev.append({"ts_ms": ts(), "round": 0, "actor": "verifier", "action": "verify", "rungs": None, "cited": [d["rule_id"]],
                   "rationale": f"{d['rule_id']} CONFIRMS: {e['summary']}", "valid": True})
    return {"evidence": evidence, "verifier": {"triggered": True, "provider": "harbor-ais", "mock": True,
                                               "budget": {"calls": 0, "spent_rlusd": "0"}}, "events": ev}


def mock_agents(k: int, ids: list[str]):
    buyer = ScriptedAgent("buyer", [
        AgentOffer(action="propose", rungs=k + 1, cited=ids, rationale="Opening anchor one rung above the evidenced ceiling."),
        AgentOffer(action="propose", rungs=k, cited=ids, rationale=f"Complying with the referee: {k} rungs, one per discrepancy, {k}% of the credit."),
        AgentOffer(action="accept", rungs=max(k - 1, 0), cited=ids[:1], rationale="Accepting the seller's counter; the oracle evidence supports the remaining rung."),
    ])
    seller = ScriptedAgent("seller", [
        AgentOffer(action="counter", rungs=max(k - 1, 0), cited=ids[:1],
                   rationale=f"Demurrage clock: 4 days x USD 150 = USD 600 already; conceding {max(k - 1, 0)} rung(s) closes today."),
        AgentOffer(action="accept", rungs=k, cited=ids, rationale="Accepting to stop the demurrage clock."),
    ])
    return buyer, seller


@app.get("/api/deal/{deal_id}/negotiate/stream")
def negotiate_stream(deal_id: str, mode: str = "live"):
    st = load_state(deal_id)
    if not st.get("examination"):
        raise HTTPException(400, "examine the deal first")
    if (st.get("escrow") or {}).get("status") == "LOCKING":
        raise HTTPException(409, "escrow lock still in progress; negotiate once the ladder is LOCKED")

    def gen():
        state = load_state(deal_id)
        if state.get("negotiation") and state["negotiation"].get("status") in ("CLOSED", "REFUSED"):
            yield _sse("meta", {"replay": True, "mode": state["negotiation"].get("mode")})
            for e in state["negotiation"]["events"]:
                yield _sse("agent", e)
            yield _sse("update", {"k": state["negotiation"]["k"], "route": state["negotiation"]["route"],
                                  "discrepancies": state["negotiation"]["discrepancies"], "evidence": state["negotiation"].get("evidence", [])})
            for s in (state.get("settlement") or {}).get("events", []):
                yield _sse("settlement", s)
            yield _sse("done", {"agreed_rungs": state["negotiation"]["agreed_rungs"], "payout": state["negotiation"]["payout"],
                                "status": state["negotiation"]["status"], "settlement": state.get("settlement")})
            return

        exam = state["examination"]
        deal = {"deal_id": deal_id, "lc_amount": str(state["lc"]["amount"]), "lc_number": state["lc"]["lc_number"],
                "applicant": state["lc"]["applicant"], "beneficiary": state["lc"]["beneficiary"]}
        ids = [d["rule_id"] for d in exam["discrepancies"]]
        live = mode == "live" and bool(os.getenv("GROQ_API_KEY"))
        w = _wallets()
        if live:
            from negotiation_agents import GroqAgent, GroqRefusalDrafter

            buyer, seller, drafter = GroqAgent("buyer"), GroqAgent("seller"), GroqRefusalDrafter()
            payer = w["_wallets"]["platform"] if w else None
            verifier = make_verifier(OracleClient(payer_wallet=payer, rpc_url=w["rpc_url"] if w else None), BudgetGuard())
        else:
            buyer, seller = mock_agents(exam["k"], ids)
            drafter, verifier = None, mock_verifier
        graph = build_graph(buyer, seller, verifier=verifier, refusal_drafter=drafter)
        yield _sse("meta", {"replay": False, "mode": "live" if live else "mock", "k": exam["k"]})
        events, final = [], None
        t0 = time.time()
        for kind, chunk in stream(graph, initial_state(deal, exam)):
            if kind == "event":
                events.append(chunk)
                yield _sse("agent", chunk)
                if chunk["actor"] == "system" and chunk["action"] == "route":
                    pass
            else:
                final = chunk
        yield _sse("update", {"k": final["k"], "route": final["route"], "discrepancies": final["discrepancies"],
                              "evidence": final.get("evidence", []), "verifier": final.get("verifier")})
        neg = {"mode": "live" if live else "mock", "events": events, "k": final["k"], "route": final["route"],
               "discrepancies": final["discrepancies"], "evidence": final.get("evidence", []), "verifier": final.get("verifier"),
               "agreed_rungs": final.get("agreed_rungs"), "payout": final.get("payout"), "status": final["status"],
               "refusal_notice": final.get("refusal_notice"), "wall_seconds": round(time.time() - t0, 2)}
        state = load_state(deal_id)
        state["negotiation"] = neg
        state["status"] = "NEGOTIATED" if final["status"] == "CLOSED" else "REFUSED"
        save_state(deal_id, state)

        m = REFUSED_M if final["status"] == "REFUSED" else final.get("agreed_rungs")
        for ev in _settle(deal_id, m):
            yield _sse("settlement", ev)
        state = load_state(deal_id)
        yield _sse("done", {"agreed_rungs": final.get("agreed_rungs"), "payout": final.get("payout"), "status": final["status"],
                            "settlement": state.get("settlement")})

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _settle(deal_id: str, m: Optional[int]):
    """Execute payout_for(m) on the ledger if the deal is locked; otherwise record the plan only."""
    st = load_state(deal_id)
    m = normalize_m(m)
    payout = payout_for(st["lc"]["amount"], m)
    esc = st.get("escrow")
    events = []
    if esc and esc.get("status") == "LOCKED":
        w = _wallets()
        eng = SettlementEngine(_ledger(), use_tickets=True)
        deal = Deal.from_dict({k: v for k, v in esc.items() if k not in ("lock_seconds",)})
        t0 = time.time()
        for ev in eng.settle_iter(deal, m, w["_wallets"]["platform"]):
            events.append(ev)
            st = load_state(deal_id)
            st["escrow"] = {**deal.to_dict(public=False), "lock_seconds": esc.get("lock_seconds")}
            if ev.get("hash"):
                feed_add(st, f"Escrow{'Finish' if ev['action'] == 'finish' else 'Cancel'} {ev['name']} {ev['amount']} RLUSD",
                         ev["hash"], ev.get("result") or "", {"kind": ev["action"], "tranche": ev["index"]})
            st["settlement"] = {"m": m, "payout": payout, "events": events, "mode": "ledger", "seconds": round(time.time() - t0, 1)}
            save_state(deal_id, st)
            yield ev
        st = load_state(deal_id)
        st["status"] = "SETTLED" if m != REFUSED_M else "REFUSED"
        save_state(deal_id, st)
    else:
        from settlement_engine import decide, tranche_plan

        plan = tranche_plan(st["lc"]["amount"])
        acts = decide(m, plan)
        for t in plan:
            ev = {"index": t.index, "name": t.name, "kind": t.kind, "amount": t.amount, "destination": t.destination,
                  "action": acts[t.index], "status": "PLANNED_" + ("RELEASE" if acts[t.index] == "finish" else "RETURN"),
                  "hash": None, "result": "not locked on ledger"}
            events.append(ev)
            yield ev
        st["settlement"] = {"m": m, "payout": payout, "events": events, "mode": "plan-only"}
        save_state(deal_id, st)


@app.post("/api/deal/{deal_id}/settle")
def settle(deal_id: str, req: SettleReq):
    st = load_state(deal_id)
    m = req.m if req.m is not None else (st.get("negotiation") or {}).get("agreed_rungs")
    if m is None and (st.get("negotiation") or {}).get("status") == "REFUSED":
        m = REFUSED_M
    events = list(_settle(deal_id, m))
    return {"m": normalize_m(m), "events": events, "deal": public_view(load_state(deal_id))}


def _do_sweep(deal_id: str) -> tuple[list[dict], dict]:
    st = load_state(deal_id)
    esc = st.get("escrow")
    if not esc or not esc.get("tranches"):
        raise HTTPException(400, "nothing locked")
    w = _wallets()
    eng = SettlementEngine(_ledger())
    deal = Deal.from_dict({k: v for k, v in esc.items() if k not in ("lock_seconds", "error")})
    deal.error = esc.get("error")
    events = list(eng.sweep_expired(deal, w["_wallets"]["platform"]))
    st["escrow"] = {**deal.to_dict(public=False), "lock_seconds": esc.get("lock_seconds")}
    for ev in events:
        feed_add(st, f"EscrowCancel {ev['name']} {ev['amount']} RLUSD (expired, returned)", ev["hash"], ev.get("result") or "",
                 {"kind": "sweep", "tranche": ev["index"]})
    save_state(deal_id, st)
    return events, st


@app.post("/api/deal/{deal_id}/sweep")
def sweep(deal_id: str):
    events, st = _do_sweep(deal_id)
    return {"swept": events, "deal": public_view(st)}


@app.get("/api/feed")
def feed(deal: Optional[str] = None, since: int = 0):
    items = []
    if deal:
        items = load_state(deal).get("ledger_feed", [])
    else:
        for d in DEALS.glob("*/state.json"):
            items += json.loads(d.read_text()).get("ledger_feed", [])
    return sorted([i for i in items if i["ts_ms"] > since], key=lambda i: i["ts_ms"])


@app.get("/api/balances")
def balances():
    w = _wallets()
    if not w:
        return {}
    lc = _ledger()
    issuer = w["wallets"]["issuer"]["address"]
    return {k: str(lc.iou_balance(v["address"], issuer)) for k, v in w["wallets"].items() if k != "issuer"}


if __name__ == "__main__":
    import uvicorn

    # hosted platforms inject PORT and need 0.0.0.0; locally stay on the loopback interface
    uvicorn.run(app, host=os.getenv("API_HOST", "127.0.0.1"), port=int(os.getenv("PORT", os.getenv("API_PORT", "8000"))))
