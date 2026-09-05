"""Team: Fozza · Product: MicroLC — settlement engine.

Money is a pure function of one integer.

    m  = number of 1% discount rungs the seller concedes (0..5), or REFUSED_M
    payout_for(lc_amount, m):
        seller   = 95% + (5 - m) x 1%
        platform = 1% fee
        buyer    = m x 1% returned
    REFUSED_M releases nothing: all 101% locked returns to the buyer at expiry.

The buyer locks 101% of the credit in seven XLS-85 escrows (base, five rungs, fee),
each gated by a PREIMAGE-SHA-256 condition whose fulfillment the platform holds.
`decide(m)` maps each tranche to "finish" or "expire"; `SettlementEngine` executes that
plan on any object that speaks the small LedgerLike protocol (real ledger or a fake).
No LLM output reaches this module.
"""
from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from typing import Iterator, Optional, Protocol

from xrpl_escrow import DEFAULT_EXPIRY_SECONDS, make_condition

BASE_PCT = Decimal("0.95")
RUNG_PCT = Decimal("0.01")
RUNG_COUNT = 5
FEE_PCT = Decimal("0.01")
LOCKED_PCT = BASE_PCT + RUNG_PCT * RUNG_COUNT + FEE_PCT  # 1.01
MAX_NEGOTIABLE_K = RUNG_COUNT  # k > 5 is refused outright
REFUSED_M = RUNG_COUNT + 1  # sentinel: release nothing

Q = Decimal("0.000001")


def money(x) -> Decimal:
    return Decimal(str(x)).quantize(Q)


def fmt(x) -> str:
    s = format(money(x).normalize(), "f")
    return "0" if s in ("-0", "0E-6") else s


# --------------------------------------------------------------------------- pure plan
@dataclass
class Tranche:
    index: int
    name: str
    kind: str  # base | rung | fee
    pct: str
    amount: str
    destination: str  # seller | platform
    condition: Optional[str] = None
    fulfillment: Optional[str] = None
    owner: Optional[str] = None
    offer_sequence: Optional[int] = None
    create_hash: Optional[str] = None
    create_result: Optional[str] = None
    cancel_after: Optional[int] = None
    status: str = "PLANNED"  # PLANNED | LOCKED | RELEASED | RETURNED | RETURN_PENDING | FAILED
    action_hash: Optional[str] = None
    action_result: Optional[str] = None

    def public(self) -> dict:
        d = asdict(self)
        d.pop("fulfillment", None)  # the fulfillment is the secret that unlocks money; never expose it
        return d


def tranche_plan(lc_amount) -> list[Tranche]:
    a = money(lc_amount)
    plan = [Tranche(0, "base", "base", fmt(BASE_PCT), fmt(a * BASE_PCT), "seller")]
    for i in range(1, RUNG_COUNT + 1):
        plan.append(Tranche(i, f"rung_{i}", "rung", fmt(RUNG_PCT), fmt(a * RUNG_PCT), "seller"))
    plan.append(Tranche(RUNG_COUNT + 1, "fee", "fee", fmt(FEE_PCT), fmt(a * FEE_PCT), "platform"))
    return plan


def total_locked(lc_amount) -> str:
    return fmt(money(lc_amount) * LOCKED_PCT)


def normalize_m(m: Optional[int]) -> int:
    """Any value outside 0..5 (including None and the refusal sentinel) means REFUSED."""
    if m is None or not isinstance(m, int) or m < 0 or m > RUNG_COUNT:
        return REFUSED_M
    return m


def decide(m: Optional[int], plan: Optional[list[Tranche]] = None) -> dict[int, str]:
    """index -> 'finish' | 'expire'. Pure."""
    m = normalize_m(m)
    plan = plan or tranche_plan(0)
    if m == REFUSED_M:
        return {t.index: "expire" for t in plan}
    keep_rungs = RUNG_COUNT - m
    out = {}
    for t in plan:
        if t.kind == "rung":
            out[t.index] = "finish" if t.index <= keep_rungs else "expire"
        else:
            out[t.index] = "finish"
    return out


def payout_for(lc_amount, m: Optional[int]) -> dict:
    """The only place amounts owed are computed. Sums always equal 101% of lc_amount."""
    m = normalize_m(m)
    plan = tranche_plan(lc_amount)
    acts = decide(m, plan)
    seller = sum((money(t.amount) for t in plan if acts[t.index] == "finish" and t.destination == "seller"), Decimal(0))
    platform = sum((money(t.amount) for t in plan if acts[t.index] == "finish" and t.destination == "platform"), Decimal(0))
    returned = sum((money(t.amount) for t in plan if acts[t.index] == "expire"), Decimal(0))
    return {
        "m": m,
        "refused": m == REFUSED_M,
        "lc_amount": fmt(lc_amount),
        "locked": total_locked(lc_amount),
        "seller": fmt(seller),
        "platform": fmt(platform),
        "buyer_returned": fmt(returned),
        "rungs_released": 0 if m == REFUSED_M else RUNG_COUNT - m,
        "discount_pct": fmt(RUNG_PCT * (0 if m == REFUSED_M else m) * 100),
    }


def payout_table(lc_amount) -> list[dict]:
    return [payout_for(lc_amount, m) for m in list(range(0, RUNG_COUNT + 1)) + [REFUSED_M]]


# --------------------------------------------------------------------------- execution
class LedgerLike(Protocol):
    def create_escrow(self, owner, destination: str, value, issuer: str, condition: str,
                      expiry_seconds: int = ..., finish_after=None, ticket_sequence=None, memo=None): ...
    def finish_escrow(self, finisher, owner: str, offer_sequence: int, condition: str, fulfillment: str): ...
    def cancel_escrow(self, canceller, owner: str, offer_sequence: int): ...
    def ledger_time(self) -> int: ...


@dataclass
class Deal:
    deal_id: str
    lc_amount: str
    issuer: str
    buyer: str
    seller: str
    platform: str
    expiry_seconds: int = DEFAULT_EXPIRY_SECONDS
    tranches: list[Tranche] = field(default_factory=list)
    m: Optional[int] = None
    status: str = "OPEN"  # OPEN | LOCKED | FAILED | SETTLED | REFUSED
    error: Optional[str] = None  # why a lock failed, in words the console can show
    rollback: list = field(default_factory=list)  # events from returning a partial lock

    def to_dict(self, public: bool = True) -> dict:
        d = asdict(self)
        d["tranches"] = [t.public() if public else asdict(t) for t in self.tranches]
        d["locked_total"] = total_locked(self.lc_amount)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Deal":
        d = dict(d)
        d.pop("locked_total", None)
        d["tranches"] = [Tranche(**t) for t in d.get("tranches", [])]
        return cls(**d)


class InsufficientFunds(RuntimeError):
    """The buyer cannot cover 101% of the credit; nothing was submitted."""

    def __init__(self, need, have):
        self.need, self.have = fmt(need), fmt(have)
        super().__init__(f"Insufficient RLUSD: need {self.need}, have {self.have} — run scripts/topup_buyer.py")


class SettlementEngine:
    def __init__(self, ledger: LedgerLike, use_tickets: bool = False):
        self.ledger = ledger
        self.use_tickets = use_tickets

    def preflight(self, buyer: str, issuer: str, lc_amount) -> None:
        """Refuse to submit a ladder the buyer cannot fund. Ledgers without balance queries skip the check."""
        query = getattr(self.ledger, "iou_balance", None)
        if query is None:
            return
        need, have = money(total_locked(lc_amount)), money(query(buyer, issuer))
        if have < need:
            raise InsufficientFunds(need, have)

    def open_deal(self, lc_amount, buyer_wallet, seller: str, platform: str, issuer: str,
                  expiry_seconds: int = DEFAULT_EXPIRY_SECONDS, deal_id: Optional[str] = None,
                  preflight: bool = True) -> Iterator[Deal]:
        """Lock 101% in seven escrows. Yields the deal after every tranche so callers can stream progress.

        Raises InsufficientFunds before anything is submitted when the buyer cannot cover the ladder.
        If some EscrowCreates land and others fail, the ones that landed are rolled back (see rollback)
        and the deal ends FAILED with every hash recorded.
        """
        deal = Deal(deal_id or uuid.uuid4().hex[:8], fmt(lc_amount), issuer, buyer_wallet.classic_address,
                    seller, platform, expiry_seconds, tranche_plan(lc_amount))
        if preflight:
            self.preflight(deal.buyer, issuer, lc_amount)
        dest = {"seller": seller, "platform": platform}
        for t in deal.tranches:
            t.condition, t.fulfillment, _ = make_condition()
            t.owner = deal.buyer
        if self.use_tickets and hasattr(self.ledger, "create_escrows_parallel"):
            specs = [{"destination": dest[t.destination], "value": t.amount, "condition": t.condition,
                      "memo": f"MicroLC {deal.deal_id} {t.name}"} for t in deal.tranches]
            results = self.ledger.create_escrows_parallel(buyer_wallet, specs, issuer, expiry_seconds)
            for t, r in zip(deal.tranches, results):
                self._record_create(t, r)
        else:
            for t in deal.tranches:
                r = self.ledger.create_escrow(buyer_wallet, dest[t.destination], t.amount, issuer, t.condition,
                                              expiry_seconds=expiry_seconds, memo=f"MicroLC {deal.deal_id} {t.name}")
                self._record_create(t, r)
                yield deal
                if not r.ok:
                    break  # do not keep locking once a tranche has failed
        if all(t.status == "LOCKED" for t in deal.tranches):
            deal.status = "LOCKED"
        else:
            deal.status = "FAILED"
            failed = [f"{t.name} {t.create_result}" for t in deal.tranches if t.status == "FAILED"]
            deal.error = f"Lock failed: {'; '.join(failed)}"
            self.rollback(deal, buyer_wallet)
        yield deal

    def rollback(self, deal: Deal, canceller) -> list[dict]:
        """Return every escrow of a partial lock to the buyer.

        rippled refuses EscrowCancel before CancelAfter (tecNO_PERMISSION), so tranches that cannot be
        cancelled yet are marked RETURN_PENDING and picked up by sweep_expired once they expire.
        """
        events = []
        for t in deal.tranches:
            if t.status != "LOCKED":
                continue
            r = self.ledger.cancel_escrow(canceller, t.owner, t.offer_sequence)
            t.action_hash, t.action_result = r.hash, r.result
            t.status = "RETURNED" if r.ok else "RETURN_PENDING"
            events.append(self._event(t, "rollback", t.status))
        deal.rollback = events
        return events

    @staticmethod
    def _record_create(t: Tranche, r) -> None:
        t.create_hash, t.offer_sequence, t.create_result = r.hash, r.offer_sequence, r.result
        t.status = "LOCKED" if r.ok else "FAILED"
        raw = getattr(r, "raw", None) or {}
        txj = raw.get("tx_json", raw) if isinstance(raw, dict) else {}
        t.cancel_after = txj.get("CancelAfter") if isinstance(txj, dict) else None

    def settle_iter(self, deal: Deal, m: Optional[int], platform_wallet) -> Iterator[dict]:
        """Execute decide(m) tranche by tranche, yielding one event per tranche."""
        m = normalize_m(m)
        deal.m = m
        acts = decide(m, deal.tranches)
        now = self.ledger.ledger_time()
        if self.use_tickets and hasattr(self.ledger, "finish_escrows_parallel"):
            yield from self._settle_parallel(deal, acts, now, platform_wallet)
            deal.status = "REFUSED" if m == REFUSED_M else "SETTLED"
            return
        for t in deal.tranches:
            action = acts[t.index]
            if t.status != "LOCKED":
                yield self._event(t, action, "skipped")
                continue
            if action == "finish":
                r = self.ledger.finish_escrow(platform_wallet, t.owner, t.offer_sequence, t.condition, t.fulfillment)
                t.action_hash, t.action_result = r.hash, r.result
                t.status = "RELEASED" if r.ok else "FAILED"
            elif t.cancel_after is not None and now > t.cancel_after:
                r = self.ledger.cancel_escrow(platform_wallet, t.owner, t.offer_sequence)
                t.action_hash, t.action_result = r.hash, r.result
                t.status = "RETURNED" if r.ok else "FAILED"
            else:
                t.status = "RETURN_PENDING"  # cannot cancel before CancelAfter; sweep later
                t.action_result = "awaiting CancelAfter"
            yield self._event(t, action, t.status)
        deal.status = "REFUSED" if m == REFUSED_M else "SETTLED"

    def _settle_parallel(self, deal: Deal, acts: dict, now: int, platform_wallet) -> Iterator[dict]:
        """All EscrowFinish (and any already-expired cancels) fired in one ledger window via Tickets."""
        to_finish = [t for t in deal.tranches if t.status == "LOCKED" and acts[t.index] == "finish"]
        to_cancel = [t for t in deal.tranches if t.status == "LOCKED" and acts[t.index] == "expire"
                     and t.cancel_after is not None and now > t.cancel_after]
        results = {}
        if to_finish:
            rs = self.ledger.finish_escrows_parallel(platform_wallet, [
                {"owner": t.owner, "offer_sequence": t.offer_sequence, "condition": t.condition,
                 "fulfillment": t.fulfillment} for t in to_finish])
            results.update({t.index: r for t, r in zip(to_finish, rs)})
        if to_cancel:
            rs = self.ledger.cancel_escrows_parallel(platform_wallet, [
                {"owner": t.owner, "offer_sequence": t.offer_sequence} for t in to_cancel])
            results.update({t.index: r for t, r in zip(to_cancel, rs)})
        for t in deal.tranches:
            action = acts[t.index]
            if t.status != "LOCKED":
                yield self._event(t, action, "skipped")
                continue
            r = results.get(t.index)
            if r is not None:
                t.action_hash, t.action_result = r.hash, r.result
                good = "RELEASED" if action == "finish" else "RETURNED"
                t.status = good if r.ok else "FAILED"
            else:
                t.status, t.action_result = "RETURN_PENDING", "awaiting CancelAfter"
            yield self._event(t, action, t.status)

    def sweep_expired(self, deal: Deal, sweeper_wallet) -> Iterator[dict]:
        """Return every expired, still-locked tranche to the buyer (anyone may cancel after CancelAfter)."""
        now = self.ledger.ledger_time()
        for t in deal.tranches:
            if t.status in ("LOCKED", "RETURN_PENDING") and t.cancel_after is not None and now > t.cancel_after:
                r = self.ledger.cancel_escrow(sweeper_wallet, t.owner, t.offer_sequence)
                t.action_hash, t.action_result = r.hash, r.result
                t.status = "RETURNED" if r.ok else "FAILED"
                yield self._event(t, "expire", t.status)

    @staticmethod
    def _event(t: Tranche, action: str, status: str) -> dict:
        return {"index": t.index, "name": t.name, "kind": t.kind, "amount": t.amount, "destination": t.destination,
                "action": action, "status": status, "hash": t.action_hash, "result": t.action_result}
