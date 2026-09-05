"""Team: Fozza · Product: MicroLC — negotiation graph (LangGraph).

    START -> verify -> route -+-> clean_close ------------------+-> apply_payout -> END
                              +-> refusal ----------------------+
                              +-> buyer -> referee -> seller -> referee ... -> default -+

* `route` is pure: clean (k == 0), negotiable (0 < k <= 5, no fatal rule), refuse (fatal or k > 5).
* The referee is pure Python. It validates every offer against the evidence:
  action is legal, rungs is an int in [0, k], citations are a subset of the discrepancy
  rule_ids (and non-empty when rungs > 0), an accept mirrors the counterparty's rungs.
  Each actor gets at most one bounce per round; a second bad offer is clamped, not argued with.
* Agents (LLM or scripted) only ever return an `AgentOffer`. They never see or touch money:
  the payout is `settlement_engine.payout_for(lc_amount, agreed_rungs)`.
* Three rounds without acceptance -> default m = k. recursion_limit = 30 covers the worst legal path.
* Every step emits a stream event {ts_ms, round, actor, action, rungs, cited, rationale} via
  get_stream_writer (stream_mode="custom"); the same dicts accumulate in state["offers"].
"""
from __future__ import annotations

import operator
import time
from typing import Annotated, Callable, Literal, Optional, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from examiner import FATAL_RULES
from settlement_engine import MAX_NEGOTIABLE_K, REFUSED_M, payout_for

MAX_ROUNDS = 3
MAX_BOUNCES_PER_ACTOR_PER_ROUND = 1
RECURSION_LIMIT = 30

Action = Literal["propose", "counter", "accept"]
Route = Literal["clean", "negotiable", "refuse"]


# --------------------------------------------------------------------------- schemas
class AgentOffer(BaseModel):
    """The only thing an agent may say. Structured output; no free text is ever parsed."""

    action: Action = Field(description="propose (opening offer), counter, or accept the counterparty's last offer")
    rungs: int = Field(description="number of 1% discount rungs the seller concedes; integer 0..k")
    cited: list[str] = Field(default_factory=list, description="discrepancy rule_ids (e.g. R15) that justify the rungs")
    rationale: str = Field(description="one sentence, <= 40 words, for the audit trail")


class Event(TypedDict, total=False):
    ts_ms: int
    round: int
    actor: str  # buyer | seller | referee | system | verifier
    action: str  # propose | counter | accept | bounce | clamped | default | route | refuse | verify
    rungs: Optional[int]
    cited: list[str]
    rationale: str
    latency_ms: Optional[int]
    valid: bool


class NegotiationState(TypedDict, total=False):
    deal: dict  # {deal_id, lc_amount, lc_number, applicant, beneficiary, ...}
    discrepancies: list[dict]
    k: int
    evidence: list[dict]  # oracle findings injected by the verifier node
    verifier: dict
    route: Route
    offers: Annotated[list[Event], operator.add]  # the only reducer: append-only trace
    pending: Optional[Event]  # offer awaiting the referee
    bounce_notice: Optional[str]
    round_no: int
    bounces: dict
    agreed_rungs: Optional[int]
    refusal_notice: Optional[str]
    payout: Optional[dict]
    status: str


# --------------------------------------------------------------------------- pure helpers
def now_ms() -> int:
    return int(time.time() * 1000)


def rule_ids(state: NegotiationState) -> set[str]:
    return {d["rule_id"] for d in state.get("discrepancies", [])}


def decide_route(k: int, discrepancies: list[dict]) -> Route:
    fatal = any(d["rule_id"] in FATAL_RULES or d.get("severity") == "fatal" for d in discrepancies)
    if fatal or k > MAX_NEGOTIABLE_K:
        return "refuse"
    return "clean" if k == 0 else "negotiable"


def opponent_last(offers: list[Event], actor: str) -> Optional[Event]:
    other = "seller" if actor == "buyer" else "buyer"
    for e in reversed(offers):
        if e["actor"] == other and e.get("valid") and e["action"] in ("propose", "counter"):
            return e
    return None


def check_offer(offer: AgentOffer, k: int, ids: set[str], opponent: Optional[Event], is_opening: bool) -> list[str]:
    """Return the list of violations (empty == legal). Pure."""
    problems = []
    if offer.action not in ("propose", "counter", "accept"):
        problems.append(f"action {offer.action!r} is not allowed")
    if is_opening and offer.action != "propose":
        problems.append("the opening offer must be a propose")
    if not is_opening and offer.action == "propose":
        problems.append("only the opening offer may be a propose; use counter or accept")
    if not isinstance(offer.rungs, int) or isinstance(offer.rungs, bool):
        problems.append("rungs must be an integer")
    elif not 0 <= offer.rungs <= k:
        problems.append(f"rungs {offer.rungs} outside the evidenced ceiling [0, {k}]")
    bad = [c for c in offer.cited if c not in ids]
    if bad:
        problems.append(f"citations {bad} are not discrepancies on this presentation")
    if offer.action != "accept" and offer.rungs > 0 and not [c for c in offer.cited if c in ids]:
        problems.append("rungs > 0 must cite at least one discrepancy rule_id")
    if offer.action == "accept":
        if opponent is None:
            problems.append("nothing to accept yet")
        elif offer.rungs != opponent["rungs"]:
            problems.append(f"accept must mirror the counterparty's {opponent['rungs']} rungs")
    return problems


def clamp_offer(offer: AgentOffer, k: int, ids: set[str], opponent: Optional[Event], is_opening: bool) -> AgentOffer:
    """Force a repeatedly illegal offer into the legal box. Pure."""
    rungs = offer.rungs if isinstance(offer.rungs, int) and not isinstance(offer.rungs, bool) else k
    rungs = max(0, min(k, rungs))
    action = offer.action
    if action == "accept" and (opponent is None or opponent["rungs"] != rungs):
        action = "propose" if is_opening else "counter"
    if is_opening:
        action = "propose"
    elif action == "propose":
        action = "counter"
    cited = [c for c in offer.cited if c in ids]
    if rungs > 0 and not cited and action != "accept":
        cited = sorted(ids)
    return AgentOffer(action=action, rungs=rungs, cited=cited, rationale=f"[clamped] {offer.rationale}"[:200])


def refusal_text(state: NegotiationState) -> str:
    lines = [f"NOTICE OF REFUSAL — credit {state['deal'].get('lc_number', '')}",
             "We have examined the presentation and refuse to honour it (UCP 600 Art. 16(c)). Discrepancies:"]
    for d in state.get("discrepancies", []):
        lines.append(f"  - {d['rule_id']} {d['code']} ({d.get('article', '')}): {d.get('message', '')}")
    for ev in state.get("evidence", []):
        if ev.get("verdict") == "CONTRADICTS":
            lines.append(f"  - external verification: {ev.get('summary', '')}")
    lines.append("Documents are held at your disposal; all escrowed funds return to the applicant at expiry.")
    return "\n".join(lines)


# --------------------------------------------------------------------------- agents
class Agent:
    """Interface. `offer` receives a context dict and returns an AgentOffer."""

    name = "agent"

    def offer(self, ctx: dict) -> AgentOffer:  # pragma: no cover - interface
        raise NotImplementedError


class ScriptedAgent(Agent):
    def __init__(self, name: str, script: list[AgentOffer]):
        self.name, self.script, self.i = name, list(script), 0
        self.seen: list[dict] = []

    def offer(self, ctx: dict) -> AgentOffer:
        self.seen.append(ctx)
        o = self.script[min(self.i, len(self.script) - 1)]
        self.i += 1
        return o


def build_context(state: NegotiationState, actor: str) -> dict:
    return {
        "actor": actor,
        "round": state.get("round_no", 1),
        "k": state["k"],
        "deal": state["deal"],
        "discrepancies": state.get("discrepancies", []),
        "evidence": state.get("evidence", []),
        "history": [e for e in state.get("offers", []) if e["actor"] in ("buyer", "seller", "referee")],
        "opponent_last": opponent_last(state.get("offers", []), actor),
        "bounce_notice": state.get("bounce_notice"),
        "is_opening": not any(e["actor"] in ("buyer", "seller") and e.get("valid") for e in state.get("offers", [])),
    }


# --------------------------------------------------------------------------- graph
def _emit(ev: Event) -> Event:
    try:
        from langgraph.config import get_stream_writer

        get_stream_writer()(ev)
    except Exception:
        pass
    return ev


def _event(actor: str, action: str, round_no: int, rungs=None, cited=None, rationale="", valid=True,
           latency_ms=None) -> Event:
    return Event(ts_ms=now_ms(), round=round_no, actor=actor, action=action, rungs=rungs, cited=list(cited or []),
                 rationale=rationale, valid=valid, latency_ms=latency_ms)


def build_graph(buyer: Agent, seller: Agent, verifier: Optional[Callable[[NegotiationState], dict]] = None,
                refusal_drafter: Optional[Callable[[NegotiationState], str]] = None):
    def verify(state: NegotiationState) -> dict:
        if verifier is None:
            return {"evidence": state.get("evidence", []), "status": "EXAMINED"}
        out = verifier(state)  # pure-code guarded; may adjust discrepancies/k and add evidence
        events = [_emit(e) for e in out.pop("events", [])]
        out.setdefault("status", "VERIFIED")
        return {**out, "offers": events}

    def route(state: NegotiationState) -> dict:
        r = decide_route(state["k"], state.get("discrepancies", []))
        ev = _emit(_event("system", "route", 0, rungs=state["k"], cited=sorted(rule_ids(state)),
                          rationale=f"k={state['k']} -> {r}"))
        return {"route": r, "round_no": 1, "bounces": {}, "offers": [ev], "status": f"ROUTED_{r.upper()}"}

    def clean_close(state: NegotiationState) -> dict:
        return {"agreed_rungs": 0, "status": "CLEAN",
                "offers": [_emit(_event("system", "accept", 0, rungs=0, rationale="complying presentation; full payout"))]}

    def refusal(state: NegotiationState) -> dict:
        text = (refusal_drafter or refusal_text)(state)
        return {"refusal_notice": text, "agreed_rungs": None, "status": "REFUSED",
                "offers": [_emit(_event("system", "refuse", 0, cited=sorted(rule_ids(state)), rationale=text[:400]))]}

    def make_actor(actor: str, agent: Agent):
        def node(state: NegotiationState) -> dict:
            t0 = time.time()
            ctx = build_context(state, actor)
            offer = agent.offer(ctx)
            ev = _event(actor, offer.action, state["round_no"], offer.rungs, offer.cited, offer.rationale,
                        valid=False, latency_ms=int((time.time() - t0) * 1000))
            _emit(ev)  # the raw offer is visible immediately; the referee's verdict follows
            return {"pending": ev, "bounce_notice": None}

        return node

    def referee(state: NegotiationState) -> dict:
        pending = state["pending"]
        actor = pending["actor"]
        k, ids = state["k"], rule_ids(state)
        offers = state.get("offers", [])
        is_opening = not any(e["actor"] in ("buyer", "seller") and e.get("valid") for e in offers)
        opp = opponent_last(offers, actor)
        offer = AgentOffer(action=pending["action"], rungs=pending["rungs"], cited=pending["cited"],
                           rationale=pending["rationale"])
        problems = check_offer(offer, k, ids, opp, is_opening)
        bounces = dict(state.get("bounces", {}))
        round_no = state["round_no"]
        out: dict = {"pending": None}
        new_events: list[Event] = []

        if problems and bounces.get(actor, 0) < MAX_BOUNCES_PER_ACTOR_PER_ROUND:
            bounces[actor] = bounces.get(actor, 0) + 1
            notice = "; ".join(problems)
            new_events.append(_emit(_event("referee", "bounce", round_no, pending["rungs"], pending["cited"],
                                           f"{actor} offer rejected: {notice}", valid=True)))
            return {**out, "bounces": bounces, "bounce_notice": notice, "offers": new_events,
                    "status": f"BOUNCED_{actor.upper()}"}
        if problems:
            offer = clamp_offer(offer, k, ids, opp, is_opening)
            new_events.append(_emit(_event("referee", "clamped", round_no, offer.rungs, offer.cited,
                                           f"{actor} offer clamped: " + "; ".join(problems), valid=True)))
        accepted = dict(pending, action=offer.action, rungs=offer.rungs, cited=list(offer.cited),
                        rationale=offer.rationale, valid=True)
        new_events.append(accepted if not problems else _emit(accepted))  # legal offers were already emitted raw
        out["offers"] = new_events

        if offer.action == "accept":
            return {**out, "agreed_rungs": offer.rungs, "status": "AGREED"}
        if actor == "seller":  # a full round (buyer + seller) is complete
            return {**out, "round_no": round_no + 1, "bounces": {}, "status": "NEXT_ROUND"}
        return {**out, "status": "SELLER_TURN"}

    def default(state: NegotiationState) -> dict:
        m = min(state["k"], MAX_NEGOTIABLE_K)
        return {"agreed_rungs": m, "status": "DEFAULTED",
                "offers": [_emit(_event("system", "default", state["round_no"], m, sorted(rule_ids(state)),
                                        f"no agreement after {MAX_ROUNDS} rounds; default m = k = {m}"))]}

    def apply_payout(state: NegotiationState) -> dict:
        m = REFUSED_M if state["status"] == "REFUSED" else state["agreed_rungs"]
        payout = payout_for(state["deal"]["lc_amount"], m)
        status = "REFUSED" if payout["refused"] else "CLOSED"
        return {"payout": payout, "status": status}

    def after_route(state: NegotiationState) -> str:
        return {"clean": "clean_close", "refuse": "refusal", "negotiable": "buyer"}[state["route"]]

    def after_referee(state: NegotiationState) -> str:
        s = state["status"]
        if s == "AGREED":
            return "apply_payout"
        if s == "BOUNCED_BUYER":
            return "buyer"
        if s == "BOUNCED_SELLER":
            return "seller"
        if s == "SELLER_TURN":
            return "seller"
        return "default" if state["round_no"] > MAX_ROUNDS else "buyer"

    g = StateGraph(NegotiationState)
    g.add_node("verify", verify)
    g.add_node("route", route)
    g.add_node("clean_close", clean_close)
    g.add_node("refusal", refusal)
    g.add_node("buyer", make_actor("buyer", buyer))
    g.add_node("seller", make_actor("seller", seller))
    g.add_node("referee", referee)
    g.add_node("default", default)
    g.add_node("apply_payout", apply_payout)
    g.add_edge(START, "verify")
    g.add_edge("verify", "route")
    g.add_conditional_edges("route", after_route, ["clean_close", "refusal", "buyer"])
    g.add_edge("clean_close", "apply_payout")
    g.add_edge("refusal", "apply_payout")
    g.add_edge("buyer", "referee")
    g.add_edge("seller", "referee")
    g.add_conditional_edges("referee", after_referee, ["apply_payout", "buyer", "seller", "default"])
    g.add_edge("default", "apply_payout")
    g.add_edge("apply_payout", END)
    return g.compile()


def initial_state(deal: dict, examination: dict) -> NegotiationState:
    """Build the graph input from a deal record and an examiner result."""
    deal = dict(deal)
    bl = (examination.get("documents") or {}).get("bill_of_lading") or {}
    if bl and "shipment" not in deal:
        deal["shipment"] = {k: bl.get(k) for k in ("bl_number", "container_number", "vessel", "voyage",
                                                    "shipped_on_board_date", "port_of_loading", "port_of_discharge")}
    return NegotiationState(deal=deal, discrepancies=list(examination["discrepancies"]), k=examination["k"],
                            evidence=[], offers=[], round_no=1, bounces={}, agreed_rungs=None, status="NEW")


def run(graph, state: NegotiationState) -> NegotiationState:
    return graph.invoke(state, config={"recursion_limit": RECURSION_LIMIT})


def stream(graph, state: NegotiationState):
    """Yield ('event', dict) for each custom event and finally ('final', state)."""
    final = None
    for mode, chunk in graph.stream(state, config={"recursion_limit": RECURSION_LIMIT},
                                    stream_mode=["custom", "values"]):
        if mode == "custom":
            yield "event", chunk
        else:
            final = chunk
    yield "final", final
