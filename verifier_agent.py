"""Team: Fozza · Product: MicroLC — verifier agent (discover -> decide -> pay -> evidence).

Sits between the examiner and the negotiation route. When a discrepancy is externally
checkable and worth checking, the agent discovers oracle providers from a registry, picks one
by policy, pays per call over x402 (XRPL AI Starter Kit client: `x402_requests`), and turns the
signed telemetry into a deterministic adjustment of the discrepancy list:

    CONFIRMS     keep the discrepancy
    CONTRADICTS  drop it and recompute k (the documents were wrong in the buyer's favour)
    MISMATCH     the transport document misstates the carriage -> FRAUD_SUSPECTED (fatal) -> refuse

Every spend decision is pure code: trigger threshold (disputed value >= 20x cheapest query),
budget guard (<= 3 calls and <= 0.25 RLUSD per deal), provider policy with a recorded reason.
An oracle failure produces a WARNING event and the deal proceeds on documents alone.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Callable, Optional

import httpx

from examiner import CHECKABLE_RULES
from negotiator_graph import Event, NegotiationState, now_ms

TRIGGER_MULTIPLE = 20  # disputed value must be >= 20x the cheapest query
MAX_CALLS_PER_DEAL = 3
MAX_SPEND_PER_DEAL = Decimal("0.25")  # RLUSD
FRAUD_RULE = {"rule_id": "R20", "code": "FRAUD_SUSPECTED", "severity": "fatal", "article": "UCP600-34",
              "checkable": False}


# --------------------------------------------------------------------------- pure guards
@dataclass
class BudgetGuard:
    max_calls: int = MAX_CALLS_PER_DEAL
    max_spend: Decimal = MAX_SPEND_PER_DEAL
    calls: int = 0
    spent: Decimal = Decimal("0")
    log: list[dict] = field(default_factory=list)

    def can_spend(self, price) -> tuple[bool, str]:
        price = Decimal(str(price))
        if self.calls >= self.max_calls:
            return False, f"call cap reached ({self.max_calls})"
        if self.spent + price > self.max_spend:
            return False, f"spend cap: {self.spent} + {price} > {self.max_spend} RLUSD"
        return True, "within budget"

    def record(self, price, provider: str, tx_hash: Optional[str]) -> None:
        self.calls += 1
        self.spent += Decimal(str(price))
        self.log.append({"provider": provider, "price": str(price), "tx_hash": tx_hash})

    def summary(self) -> dict:
        return {"calls": self.calls, "spent_rlusd": str(self.spent), "max_calls": self.max_calls,
                "max_spend_rlusd": str(self.max_spend), "log": self.log}


def checkable_discrepancies(discrepancies: list[dict]) -> list[dict]:
    return [d for d in discrepancies if d.get("checkable") or d.get("rule_id") in CHECKABLE_RULES]


def disputed_value(lc_amount, checkable: list[dict]) -> Decimal:
    """One 1% rung is at stake per checkable discrepancy."""
    return Decimal(str(lc_amount)) * Decimal("0.01") * len(checkable)


def should_verify(lc_amount, discrepancies: list[dict], cheapest_price) -> tuple[bool, str]:
    chk = checkable_discrepancies(discrepancies)
    if not chk:
        return False, "no externally checkable discrepancy"
    value = disputed_value(lc_amount, chk)
    threshold = Decimal(str(cheapest_price)) * TRIGGER_MULTIPLE
    if value < threshold:
        return False, f"disputed value {value} RLUSD < {TRIGGER_MULTIPLE}x cheapest query ({threshold})"
    return True, f"disputed value {value} RLUSD >= {TRIGGER_MULTIPLE}x cheapest query ({threshold})"


def needed_fields(checkable: list[dict]) -> set[str]:
    need = set()
    for d in checkable:
        r = d["rule_id"]
        if r == "R15":
            need.add("atd")
        elif r in ("R18", "R19"):
            need.update({"vessel", "container_number"})
        elif r == "R12":
            need.add("port_of_loading")
        elif r == "R13":
            need.add("port_of_discharge")
    return need


def choose_provider(providers: list[dict], need: set[str], budget: BudgetGuard) -> tuple[Optional[dict], str]:
    """Policy: cheapest provider that covers every needed field and fits the budget; tie -> lower latency."""
    fits = [p for p in providers if need <= set(p.get("coverage", [])) and budget.can_spend(p["price_rlusd"])[0]]
    if not fits:
        covering = [p["id"] for p in providers if need <= set(p.get("coverage", []))]
        return None, f"no provider covers {sorted(need)} within budget (covering: {covering})"
    fits.sort(key=lambda p: (Decimal(p["price_rlusd"]), p.get("latency_ms", 0)))
    best = fits[0]
    others = [f"{p['id']}@{p['price_rlusd']}" for p in providers if p is not best]
    return best, (f"chose {best['id']} at {best['price_rlusd']} RLUSD ({best.get('latency_ms')}ms): cheapest provider "
                  f"covering {sorted(need)}; alternatives {others}")


def judge(disc: dict, shipment: dict, telemetry: dict) -> tuple[str, str]:
    """Map oracle telemetry to CONFIRMS / CONTRADICTS / MISMATCH for one discrepancy. Pure."""
    r = disc["rule_id"]
    t = telemetry
    if r == "R15":
        bl_date, latest, atd = str(disc.get("found")), str(disc.get("expected")), str(t.get("atd"))
        if atd == bl_date:
            return "CONFIRMS", f"oracle ATD {atd} equals the B/L on-board date; shipment was late by evidence"
        if atd <= latest:
            return "CONTRADICTS", f"oracle ATD {atd} is on or before the latest shipment date {latest}; B/L date is a clerical error"
        return "MISMATCH", f"oracle ATD {atd} differs from the B/L on-board date {bl_date}"
    if r in ("R18", "R19"):
        bl_vessel = str(shipment.get("vessel") or disc.get("expected"))
        bl_cont = str(shipment.get("container_number") or disc.get("expected"))
        o_vessel, o_cont = str(t.get("vessel")), str(t.get("container_number"))
        if _n(o_vessel) == _n(bl_vessel) and _n(o_cont) == _n(bl_cont):
            return "CONFIRMS", f"carrier record: {o_cont} sailed on {o_vessel}; the B/L is right, the packing list is wrong"
        return "MISMATCH", f"carrier record shows {o_cont} on {o_vessel}, but the B/L states {bl_cont} on {bl_vessel}"
    if r in ("R12", "R13"):
        key = "port_of_loading" if r == "R12" else "port_of_discharge"
        o = str(t.get(key))
        if _n(o) == _n(str(disc.get("expected"))):
            return "CONTRADICTS", f"oracle {key} {o} matches the credit; the B/L entry is a clerical error"
        if _n(o) == _n(str(disc.get("found"))):
            return "CONFIRMS", f"oracle {key} {o} matches the B/L; goods really moved via a different port"
        return "MISMATCH", f"oracle {key} {o} matches neither the credit nor the B/L"
    return "UNKNOWN", "no verdict rule for this discrepancy"


def _n(s: str) -> str:
    return "".join(ch for ch in s.lower() if ch.isalnum())


def apply_verdicts(discrepancies: list[dict], verdicts: list[dict]) -> tuple[list[dict], int]:
    """Deterministic k adjustment. verdicts: [{rule_id, verdict, summary}]."""
    by_rule = {v["rule_id"]: v for v in verdicts}
    out = []
    fraud = None
    for d in discrepancies:
        v = by_rule.get(d["rule_id"])
        if v is None or v["verdict"] in ("CONFIRMS", "UNKNOWN", "UNAVAILABLE"):
            out.append(d)
        elif v["verdict"] == "CONTRADICTS":
            continue  # dropped
        elif v["verdict"] == "MISMATCH":
            out.append(d)
            fraud = fraud or {**FRAUD_RULE, "doc": d.get("doc"), "field": d.get("field"), "found": d.get("found"),
                              "expected": d.get("expected"), "message": f"External evidence contradicts the transport document: {v['summary']}",
                              "article_text": "Fraud exception: a bank need not honour where the transport document misrepresents the shipment."}
    if fraud:
        out.append(fraud)
    return out, len(out)


# --------------------------------------------------------------------------- oracle client (x402)
class OracleClient:
    """Discovers the registry and makes paid calls with the starter kit's x402 requests session."""

    def __init__(self, registry_url: Optional[str] = None, payer_wallet=None, rpc_url: Optional[str] = None,
                 session=None, timeout: float = 120.0):
        self.registry_url = (registry_url or os.getenv("ORACLE_URL", "http://127.0.0.1:8001")).rstrip("/") + "/registry"
        self.timeout = timeout
        self._session = session
        self._payer = payer_wallet
        self._rpc = rpc_url or os.getenv("XRPL_RPC_URL", "https://s.altnet.rippletest.net:51234/")

    def discover(self) -> dict:
        r = httpx.get(self.registry_url, timeout=15)
        r.raise_for_status()
        return r.json()

    def session(self):
        if self._session is None:
            from x402_xrpl.clients import x402_requests

            self._session = x402_requests(self._payer, rpc_url=self._rpc, network_filter=os.getenv("XRPL_NETWORK", "xrpl:1"),
                                          scheme_filter="exact")
        return self._session

    def query(self, provider: dict, params: dict) -> dict:
        """Returns {"ok", "status", "body", "tx_hash", "latency_ms", "paid"}."""
        from x402_xrpl.clients import decode_payment_response

        t0 = time.time()
        resp = self.session().get(provider["endpoint"], params=params, timeout=self.timeout)
        latency = int((time.time() - t0) * 1000)
        tx_hash = None
        if "PAYMENT-RESPONSE" in resp.headers:
            try:
                tx_hash = decode_payment_response(resp.headers["PAYMENT-RESPONSE"]).get("transaction")
            except Exception:
                tx_hash = None
        body = None
        try:
            body = resp.json()
        except Exception:
            pass
        return {"ok": resp.status_code == 200, "status": resp.status_code, "body": body, "tx_hash": tx_hash,
                "latency_ms": latency, "paid": tx_hash is not None}


# --------------------------------------------------------------------------- graph node
def make_verifier(client: OracleClient, budget: Optional[BudgetGuard] = None,
                  discover: Optional[Callable[[], dict]] = None) -> Callable[[NegotiationState], dict]:
    """Return a LangGraph node: state -> {discrepancies, k, evidence, verifier, events}."""

    def node(state: NegotiationState) -> dict:
        guard = budget or BudgetGuard()
        deal = state["deal"]
        discs = list(state.get("discrepancies", []))
        events: list[Event] = []
        info: dict = {"triggered": False, "reason": "", "provider": None, "budget": guard.summary()}

        def ev(action: str, rationale: str, cited=None, rungs=None) -> None:
            events.append(Event(ts_ms=now_ms(), round=0, actor="verifier", action=action, rungs=rungs,
                                cited=list(cited or []), rationale=rationale, valid=True))

        chk = checkable_discrepancies(discs)
        if not chk:
            info["reason"] = "no externally checkable discrepancy"
            ev("skip", info["reason"])
            return {"discrepancies": discs, "k": len(discs), "evidence": [], "verifier": info, "events": events}

        try:
            registry = (discover or client.discover)()
            providers = registry["providers"]
        except Exception as exc:
            info["reason"] = f"registry unavailable: {type(exc).__name__}"
            ev("warning", f"oracle registry unreachable ({type(exc).__name__}); proceeding on documents alone")
            return {"discrepancies": discs, "k": len(discs), "evidence": [], "verifier": info, "events": events}

        cheapest = min(Decimal(p["price_rlusd"]) for p in providers)
        go, why = should_verify(deal["lc_amount"], discs, cheapest)
        info["reason"] = why
        ev("discover", f"{len(providers)} providers: " + ", ".join(f"{p['id']}@{p['price_rlusd']} RLUSD/{p.get('latency_ms')}ms" for p in providers),
           cited=[d["rule_id"] for d in chk])
        if not go:
            ev("skip", why)
            return {"discrepancies": discs, "k": len(discs), "evidence": [], "verifier": info, "events": events}
        info["triggered"] = True

        need = needed_fields(chk)
        provider, choice = choose_provider(providers, need, guard)
        ev("decide", choice)
        if provider is None:
            info["budget"] = guard.summary()
            return {"discrepancies": discs, "k": len(discs), "evidence": [], "verifier": info, "events": events}
        info["provider"] = provider["id"]

        ship = deal.get("shipment") or {}
        params = {"bl": ship.get("bl_number") or "", "container": ship.get("container_number") or ""}
        ok, reason = guard.can_spend(provider["price_rlusd"])
        if not ok:
            ev("warning", f"budget guard refused: {reason}")
            return {"discrepancies": discs, "k": len(discs), "evidence": [], "verifier": info, "events": events}
        try:
            res = client.query(provider, params)
        except Exception as exc:
            ev("warning", f"oracle call failed ({type(exc).__name__}); proceeding on documents alone")
            info["budget"] = guard.summary()
            return {"discrepancies": discs, "k": len(discs), "evidence": [], "verifier": info, "events": events}
        if res.get("paid"):
            guard.record(provider["price_rlusd"], provider["id"], res["tx_hash"])
            ev("pay", f"paid {provider['price_rlusd']} RLUSD to {provider['id']} via x402 (tx {res['tx_hash']}) in {res['latency_ms']}ms",
               cited=[res["tx_hash"]])
        if not res.get("ok"):
            detail = (res.get("body") or {}).get("detail") or (res.get("body") or {}).get("error") or res.get("status")
            ev("warning", f"oracle returned {res.get('status')}: {detail}; proceeding on documents alone")
            info["budget"] = guard.summary()
            return {"discrepancies": discs, "k": len(discs),
                    "evidence": [{"rule_id": d["rule_id"], "verdict": "UNAVAILABLE", "summary": str(detail)} for d in chk],
                    "verifier": info, "events": events}

        telemetry = (res["body"] or {}).get("telemetry", {})
        verdicts = []
        for d in chk:
            verdict, summary = judge(d, ship, telemetry)
            verdicts.append({"rule_id": d["rule_id"], "verdict": verdict, "summary": summary, "provider": provider["id"],
                             "tx_hash": res["tx_hash"], "price_rlusd": provider["price_rlusd"], "telemetry": telemetry,
                             "signature": (res["body"] or {}).get("signature")})
            ev("verify", f"{d['rule_id']} {verdict}: {summary}", cited=[d["rule_id"]])
        new_discs, k = apply_verdicts(discs, verdicts)
        if k != len(discs) or any(v["verdict"] == "MISMATCH" for v in verdicts):
            ev("adjust", f"k {len(discs)} -> {k}" + ("; FRAUD_SUSPECTED raised" if any(d.get('rule_id') == 'R20' for d in new_discs) else ""),
               rungs=k, cited=[d["rule_id"] for d in new_discs])
        info["budget"] = guard.summary()
        return {"discrepancies": new_discs, "k": k, "evidence": verdicts, "verifier": info, "events": events}

    return node
