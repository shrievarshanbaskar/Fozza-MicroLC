"""Team: Fozza · Product: MicroLC — LLM negotiation agents (langchain-groq, structured output only).

Buyer, seller and refusal drafter are thin personas around `ChatGroq.with_structured_output`.
They can only return an `AgentOffer` (or `RefusalNotice`); the pure-code referee in
negotiator_graph decides whether an offer is legal, and settlement_engine decides money.
Prompts are kept short (about 1.2k tokens per call) to live inside an 8k tokens-per-minute budget.
Model IDs come from .env (GROQ_LARGE_MODEL); nothing is hard-coded here.
"""
from __future__ import annotations

import json
import os
from typing import Optional

from dotenv import load_dotenv
from langchain_groq import ChatGroq
from pydantic import BaseModel, Field

from negotiator_graph import Agent, AgentOffer, NegotiationState, refusal_text
from ucp_articles import cite

load_dotenv()

DEMURRAGE_PER_DAY_USD = 150

SYSTEM_COMMON = (
    "You negotiate the settlement of a documentary letter of credit (UCP 600). The bank's examiner found k "
    "discrepancies. Settlement is a ladder: the seller may concede whole 1% 'rungs' of the credit amount, at most "
    "one rung per discrepancy, so rungs is an integer in [0, k]. A pure-code referee rejects any offer whose rungs "
    "leave [0, k], whose citations are not real rule_ids, or whose 'accept' does not mirror the counterparty's rungs. "
    "You output ONLY the structured offer. Keep the rationale to one sentence with concrete numbers. When external "
    "verification evidence is listed, name the provider and its verdict in your rationale (e.g. 'harbor-ais CONFIRMS "
    "the late ATD'); paid, signed evidence outranks either party's assertions."
)

BUYER_PERSONA = (
    "ROLE: BUYER (applicant). You want the largest lawful discount. Tactics: on your OPENING offer anchor ONE rung "
    "above the evidenced ceiling k to test the referee; the referee will bounce it. After a bounce, comply exactly "
    "with the notice and propose k rungs citing every discrepancy. In later rounds accept the seller's counter if it "
    "concedes at least k-1 rungs, otherwise counter at k. Never propose below the seller's last counter."
)

SELLER_PERSONA = (
    "ROLE: SELLER (beneficiary). Every day of delay costs you demurrage of USD {dem}/day at the discharge port, so a "
    "fast close is worth money: show the arithmetic (days x {dem} = USD total) in your rationale and compare it with "
    "the RLUSD value of the rungs in dispute (1 rung = 1% of the credit). Counter with fewer rungs than the buyer "
    "proposed only for discrepancies you can argue are immaterial; cite the rule_ids you concede. Accept when the "
    "buyer's ask is within one rung of yours or when demurrage exceeds the disputed value."
)


class RefusalNotice(BaseModel):
    text: str = Field(description="UCP 600 Art. 16(c) refusal notice, <= 120 words, plain text")
    cited_articles: list[str] = Field(default_factory=list, description="article references quoted")


def _llm(max_tokens: int, temperature: float) -> ChatGroq:
    # gpt-oss style models spend tokens on reasoning before the JSON; a tight max_tokens with default
    # effort returns an empty generation (json_validate_failed). Low effort + 600 tokens is reliable.
    return ChatGroq(model=os.environ["GROQ_LARGE_MODEL"], temperature=temperature, max_tokens=max_tokens,
                    reasoning_effort="low")


def render_context(ctx: dict) -> str:
    deal = ctx["deal"]
    lines = [
        f"Credit {deal.get('lc_number', '')}: amount {deal.get('lc_amount')} RLUSD; 1 rung = "
        f"{float(deal.get('lc_amount', 0)) / 100:.2f} RLUSD. k = {ctx['k']}. Round {ctx['round']} of 3.",
        "Discrepancies (rule_id | code | field | found vs expected | article):",
    ]
    for d in ctx["discrepancies"]:
        lines.append(f"  {d['rule_id']} | {d['code']} | {d.get('field')} | {d.get('found')} vs {d.get('expected')} | "
                     f"{cite(d.get('article', ''))[:110]}")
    days = int(deal.get("days_delayed", 4)) + max(0, ctx["round"] - 1)
    lines.append(f"Demurrage clock: {days} day(s) of delay so far at USD {DEMURRAGE_PER_DAY_USD}/day = "
                 f"USD {days * DEMURRAGE_PER_DAY_USD}; each further round adds one day.")
    if ctx.get("evidence"):
        lines.append("External verification (paid oracle, on-ledger receipt):")
        for ev in ctx["evidence"]:
            lines.append(f"  {ev.get('rule_id')}: {ev.get('verdict')} — {ev.get('summary', '')[:160]}")
    hist = ctx.get("history", [])[-6:]
    if hist:
        lines.append("Offer history (actor action rungs cited):")
        for e in hist:
            lines.append(f"  r{e['round']} {e['actor']} {e['action']} {e.get('rungs')} {e.get('cited')} — {e.get('rationale', '')[:90]}")
    opp = ctx.get("opponent_last")
    if opp:
        lines.append(f"Counterparty's standing offer: {opp['rungs']} rungs (accept must mirror this number).")
    if ctx.get("bounce_notice"):
        lines.append(f"REFEREE BOUNCE NOTICE: {ctx['bounce_notice']}. Your next offer must comply.")
    allowed = "propose" if ctx.get("is_opening") else ("counter or accept" if opp else "counter")
    lines.append(f"Allowed action now: {allowed}.")
    return "\n".join(lines)


class GroqAgent(Agent):
    def __init__(self, role: str, temperature: float = 0.3, max_tokens: int = 600):
        assert role in ("buyer", "seller")
        self.name = role
        self.persona = BUYER_PERSONA if role == "buyer" else SELLER_PERSONA.format(dem=DEMURRAGE_PER_DAY_USD)
        self.chain = _llm(max_tokens, temperature).with_structured_output(AgentOffer, method="json_schema")
        self.calls: list[dict] = []

    def offer(self, ctx: dict) -> AgentOffer:
        prompt = [("system", SYSTEM_COMMON + "\n" + self.persona), ("human", render_context(ctx))]
        try:
            out = self.chain.invoke(prompt)
            self.calls.append({"ok": True, "offer": out.model_dump()})
            return out
        except Exception as exc:  # model/network failure: a legal, conservative offer keeps the deal moving
            fallback = self._fallback(ctx, f"{type(exc).__name__}")
            self.calls.append({"ok": False, "error": str(exc)[:200], "offer": fallback.model_dump()})
            return fallback

    def _fallback(self, ctx: dict, why: str) -> AgentOffer:
        ids = [d["rule_id"] for d in ctx["discrepancies"]]
        opp = ctx.get("opponent_last")
        if ctx.get("is_opening"):
            return AgentOffer(action="propose", rungs=ctx["k"], cited=ids, rationale=f"[fallback {why}] propose k")
        if opp is not None:
            return AgentOffer(action="accept", rungs=opp["rungs"], cited=list(opp["cited"]),
                              rationale=f"[fallback {why}] accept standing offer")
        return AgentOffer(action="counter", rungs=ctx["k"], cited=ids, rationale=f"[fallback {why}] counter k")


class GroqRefusalDrafter:
    def __init__(self, temperature: float = 0.2, max_tokens: int = 300):
        self.chain = _llm(max_tokens, temperature).with_structured_output(RefusalNotice, method="json_schema")

    def __call__(self, state: NegotiationState) -> str:
        skeleton = refusal_text(state)  # pure-code facts; the model only phrases them
        try:
            out = self.chain.invoke([
                ("system", "You draft a UCP 600 Article 16(c) notice of refusal for a bank. Use ONLY the facts given; "
                           "quote each discrepancy's rule_id and article; state that documents are held at the "
                           "presenter's disposal and escrowed funds return to the applicant. <= 120 words."),
                ("human", skeleton),
            ])
            return out.text
        except Exception:
            return skeleton


def default_agents(live: bool = True) -> tuple[Agent, Agent, Optional[GroqRefusalDrafter]]:
    if live and os.getenv("GROQ_API_KEY"):
        return GroqAgent("buyer"), GroqAgent("seller"), GroqRefusalDrafter()
    from negotiator_graph import ScriptedAgent

    return ScriptedAgent("buyer", []), ScriptedAgent("seller", []), None


if __name__ == "__main__":
    import sys

    from negotiator_graph import build_context

    ctx = json.load(open(sys.argv[1])) if len(sys.argv) > 1 else None
    print(render_context(ctx) if ctx else "usage: python negotiation_agents.py <ctx.json>")
