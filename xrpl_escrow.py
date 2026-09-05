"""Team: Fozza · Product: MicroLC — XRPL ledger layer.

Thin, synchronous wrapper around xrpl-py for everything MicroLC does on the XRP Ledger:

* testnet faucet funding and RLUSD (IOU) trust lines / issuance
* XLS-85 token escrows (EscrowCreate / EscrowFinish / EscrowCancel on an issued currency)
  gated by PREIMAGE-SHA-256 crypto-conditions
* optional Ticket-based parallel EscrowCreate submission
* balance and ledger-time queries

Nothing in this module makes a decision about money; it only executes instructions
that the pure settlement engine hands it.
"""
from __future__ import annotations

import hashlib
import os
import secrets
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, Optional

from xrpl.clients import JsonRpcClient
from xrpl.models.amounts import IssuedCurrencyAmount
from xrpl.models.requests import AccountInfo, AccountLines, Ledger, Tx
from xrpl.models.transactions import (
    AccountSet,
    AccountSetAsfFlag,
    EscrowCancel,
    EscrowCreate,
    EscrowFinish,
    Payment,
    TicketCreate,
    TrustSet,
)
from xrpl.models.transactions.transaction import Transaction
from xrpl.transaction import autofill_and_sign, submit, submit_and_wait
from xrpl.asyncio.transaction.reliable_submission import XRPLReliableSubmissionException
from xrpl.utils import ripple_time_to_datetime
from xrpl.wallet import Wallet, generate_faucet_wallet

RLUSD_HEX = "524C555344000000000000000000000000000000"  # "RLUSD" left-padded to 160 bits
RIPPLE_EPOCH_OFFSET = 946_684_800  # seconds between Unix epoch and 2000-01-01T00:00Z
DEFAULT_RPC = os.getenv("XRPL_RPC_URL", "https://s.altnet.rippletest.net:51234/")
DEFAULT_EXPIRY_SECONDS = int(os.getenv("ESCROW_EXPIRY_SECONDS", "180"))
EXPLORER_TX = "https://testnet.xrpl.org/transactions/{}"
EXPLORER_ACCOUNT = "https://testnet.xrpl.org/accounts/{}"


# --------------------------------------------------------------------------- crypto-conditions
def make_condition(preimage: Optional[bytes] = None) -> tuple[str, str, str]:
    """Return (condition_hex, fulfillment_hex, preimage_hex) for a PREIMAGE-SHA-256 condition.

    DER layout (RFC crypto-conditions draft, type 0 = PREIMAGE-SHA-256):
      condition   = A0 <len> 80 20 <sha256(preimage)> 81 <len> <cost>
      fulfillment = A0 <len> 80 <len> <preimage>
    where cost = len(preimage). A 32-byte preimage gives the familiar A0258020…810120 prefix.
    """
    preimage = preimage if preimage is not None else secrets.token_bytes(32)
    if not 1 <= len(preimage) <= 127:
        raise ValueError("preimage must be 1..127 bytes for single-byte DER lengths")
    fingerprint = hashlib.sha256(preimage).digest()
    cost = _der_uint(len(preimage))
    cond_body = b"\x80\x20" + fingerprint + b"\x81" + bytes([len(cost)]) + cost
    condition = b"\xa0" + bytes([len(cond_body)]) + cond_body
    ful_body = b"\x80" + bytes([len(preimage)]) + preimage
    fulfillment = b"\xa0" + bytes([len(ful_body)]) + ful_body
    return condition.hex().upper(), fulfillment.hex().upper(), preimage.hex().upper()


def _der_uint(n: int) -> bytes:
    out = n.to_bytes((n.bit_length() + 7) // 8 or 1, "big")
    return b"\x00" + out if out[0] & 0x80 else out


def verify_fulfillment(condition_hex: str, fulfillment_hex: str) -> bool:
    """Pure check that a fulfillment satisfies a condition (mirrors what rippled does)."""
    ful = bytes.fromhex(fulfillment_hex)
    if ful[:1] != b"\xa0" or ful[2:3] != b"\x80":
        return False
    preimage = ful[4 : 4 + ful[3]]
    return make_condition(preimage)[0] == condition_hex.upper()


# --------------------------------------------------------------------------- time helpers
def ripple_now() -> int:
    return int(time.time()) - RIPPLE_EPOCH_OFFSET


def ripple_to_iso(t: int) -> str:
    return ripple_time_to_datetime(t).isoformat()


# --------------------------------------------------------------------------- results
@dataclass
class TxResult:
    ok: bool
    hash: str
    result: str
    sequence: Optional[int] = None
    ticket_sequence: Optional[int] = None
    ledger_index: Optional[int] = None
    raw: Optional[dict] = None

    @property
    def offer_sequence(self) -> Optional[int]:
        """The value an EscrowFinish/EscrowCancel must quote as OfferSequence."""
        return self.ticket_sequence if self.ticket_sequence else self.sequence

    @property
    def explorer(self) -> str:
        return EXPLORER_TX.format(self.hash)

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "hash": self.hash,
            "result": self.result,
            "sequence": self.sequence,
            "ticket_sequence": self.ticket_sequence,
            "ledger_index": self.ledger_index,
            "explorer": self.explorer,
        }


class LedgerError(RuntimeError):
    pass


# --------------------------------------------------------------------------- client
class LedgerClient:
    def __init__(self, rpc_url: str = DEFAULT_RPC, currency: str = RLUSD_HEX):
        self.rpc_url = rpc_url
        self.client = JsonRpcClient(rpc_url)
        self.currency = currency

    # ---- funding / setup ------------------------------------------------------------
    def fund_wallet(self, attempts: int = 4) -> Wallet:
        last: Exception | None = None
        for i in range(attempts):
            try:
                return generate_faucet_wallet(self.client, debug=False)
            except Exception as exc:  # faucet is flaky; back off and retry
                last = exc
                time.sleep(3 * (i + 1))
        raise LedgerError(f"faucet failed after {attempts} attempts: {last}")

    def enable_issuer_flags(self, issuer: Wallet) -> list[TxResult]:
        """asfAllowTrustLineLocking (17) lets IOUs be escrowed; asfDefaultRipple lets holders pay each other."""
        out = []
        for flag in (AccountSetAsfFlag.ASF_ALLOW_TRUSTLINE_LOCKING, AccountSetAsfFlag.ASF_DEFAULT_RIPPLE):
            out.append(self.submit(AccountSet(account=issuer.classic_address, set_flag=flag), issuer))
        return out

    def create_trustline(self, holder: Wallet, issuer: str, limit: str = "1000000000") -> TxResult:
        tx = TrustSet(
            account=holder.classic_address,
            limit_amount=IssuedCurrencyAmount(currency=self.currency, issuer=issuer, value=limit),
        )
        return self.submit(tx, holder)

    def issue(self, issuer: Wallet, destination: str, value: str) -> TxResult:
        return self.pay_iou(issuer, destination, value, issuer.classic_address)

    def pay_iou(self, sender: Wallet, destination: str, value: str, issuer: str,
                memos=None, invoice_id: Optional[str] = None) -> TxResult:
        tx = Payment(
            account=sender.classic_address,
            destination=destination,
            amount=self.amount(value, issuer),
            memos=memos,
            invoice_id=invoice_id,
        )
        return self.submit(tx, sender)

    def amount(self, value, issuer: str) -> IssuedCurrencyAmount:
        return IssuedCurrencyAmount(currency=self.currency, issuer=issuer, value=_money(value))

    # ---- escrows ----------------------------------------------------------------------
    def create_escrow(self, owner: Wallet, destination: str, value, issuer: str, condition: str,
                      expiry_seconds: int = DEFAULT_EXPIRY_SECONDS, finish_after: Optional[int] = None,
                      ticket_sequence: Optional[int] = None, memo: Optional[str] = None) -> TxResult:
        """XLS-85 token escrow. IOU escrows MUST carry CancelAfter (temBAD_EXPIRATION otherwise)."""
        cancel_after = ripple_now() + int(expiry_seconds)
        kwargs = dict(
            account=owner.classic_address,
            destination=destination,
            amount=self.amount(value, issuer),
            condition=condition,
            cancel_after=cancel_after,
            finish_after=finish_after,
            memos=_memos(memo),
        )
        if ticket_sequence is not None:
            kwargs.update(ticket_sequence=ticket_sequence, sequence=0)
        res = self.submit(EscrowCreate(**kwargs), owner)
        res.ticket_sequence = ticket_sequence
        return res

    def finish_escrow(self, finisher: Wallet, owner: str, offer_sequence: int,
                      condition: str, fulfillment: str) -> TxResult:
        tx = EscrowFinish(
            account=finisher.classic_address,
            owner=owner,
            offer_sequence=offer_sequence,
            condition=condition,
            fulfillment=fulfillment,
        )
        return self.submit(tx, finisher)

    def cancel_escrow(self, canceller: Wallet, owner: str, offer_sequence: int) -> TxResult:
        tx = EscrowCancel(account=canceller.classic_address, owner=owner, offer_sequence=offer_sequence)
        return self.submit(tx, canceller)

    # ---- tickets (parallel EscrowCreate) -----------------------------------------------
    def create_tickets(self, owner: Wallet, count: int) -> list[int]:
        res = self.submit(TicketCreate(account=owner.classic_address, ticket_count=count), owner)
        if not res.ok or res.sequence is None:
            raise LedgerError(f"TicketCreate failed: {res.result}")
        return [res.sequence + i for i in range(1, count + 1)]

    def create_escrows_parallel(self, owner: Wallet, specs: Iterable[dict], issuer: str,
                                expiry_seconds: int = DEFAULT_EXPIRY_SECONDS) -> list[TxResult]:
        """Submit one EscrowCreate per spec in the same ledger window using Tickets.

        spec = {"destination", "value", "condition", "memo"?}. Returns results in spec order.
        The escrow's OfferSequence (needed later by EscrowFinish/Cancel) is the TicketSequence.
        """
        specs = list(specs)
        cancel_after = ripple_now() + int(expiry_seconds)
        txs = [EscrowCreate(account=owner.classic_address, destination=s["destination"],
                            amount=self.amount(s["value"], issuer), condition=s["condition"],
                            cancel_after=cancel_after, memos=_memos(s.get("memo"))) for s in specs]
        return self.submit_parallel(owner, txs)

    def finish_escrows_parallel(self, finisher: Wallet, items: Iterable[dict]) -> list[TxResult]:
        """item = {"owner", "offer_sequence", "condition", "fulfillment"}; all EscrowFinish in one ledger window."""
        txs = [EscrowFinish(account=finisher.classic_address, owner=i["owner"], offer_sequence=i["offer_sequence"],
                            condition=i["condition"], fulfillment=i["fulfillment"]) for i in items]
        return self.submit_parallel(finisher, txs)

    def cancel_escrows_parallel(self, canceller: Wallet, items: Iterable[dict]) -> list[TxResult]:
        txs = [EscrowCancel(account=canceller.classic_address, owner=i["owner"], offer_sequence=i["offer_sequence"])
               for i in items]
        return self.submit_parallel(canceller, txs)

    def submit_parallel(self, wallet: Wallet, txs: list[Transaction]) -> list[TxResult]:
        """TicketCreate(n), then sign each tx with its TicketSequence (Sequence=0), fire concurrently, wait for all."""
        if not txs:
            return []
        tickets = self.create_tickets(wallet, len(txs))
        signed = [autofill_and_sign(_with_ticket(tx, t), self.client, wallet) for tx, t in zip(txs, tickets)]

        def _fire(stx: Transaction) -> str:
            resp = submit(stx, self.client).result
            eng = resp.get("engine_result", "")
            if not (eng == "tesSUCCESS" or eng.startswith("ter")):
                raise LedgerError(f"submit rejected: {eng}")
            return resp["tx_json"]["hash"]

        with ThreadPoolExecutor(max_workers=len(signed)) as pool:
            hashes = list(pool.map(_fire, signed))
        results = [self.wait_for_tx(h) for h in hashes]
        for r, t in zip(results, tickets):
            r.ticket_sequence = t
        return results

    def wait_for_tx(self, tx_hash: str, timeout: float = 60.0) -> TxResult:
        deadline = time.time() + timeout
        while time.time() < deadline:
            r = self.client.request(Tx(transaction=tx_hash)).result
            if r.get("validated"):
                meta = r.get("meta", {})
                code = meta.get("TransactionResult", "unknown") if isinstance(meta, dict) else "unknown"
                txj = r.get("tx_json", r)
                return TxResult(code == "tesSUCCESS", tx_hash, code, txj.get("Sequence"),
                                txj.get("TicketSequence"), r.get("ledger_index"), r)
            time.sleep(1.0)
        return TxResult(False, tx_hash, "timeout")

    # ---- queries -----------------------------------------------------------------------
    def iou_balance(self, address: str, issuer: str) -> Decimal:
        lines = self.client.request(AccountLines(account=address, peer=issuer)).result.get("lines", [])
        for line in lines:
            if line.get("currency") == self.currency:
                return Decimal(line["balance"])
        return Decimal("0")

    def xrp_balance(self, address: str) -> Decimal:
        info = self.client.request(AccountInfo(account=address, ledger_index="validated")).result
        return Decimal(info["account_data"]["Balance"]) / Decimal(1_000_000)

    def ledger_time(self) -> int:
        """Close time (ripple epoch) of the latest validated ledger."""
        r = self.client.request(Ledger(ledger_index="validated")).result
        return int(r["ledger"]["close_time"])

    def sequence(self, address: str) -> int:
        return self.client.request(AccountInfo(account=address)).result["account_data"]["Sequence"]

    # ---- submission --------------------------------------------------------------------
    def submit(self, tx: Transaction, wallet: Wallet, retries: int = 2) -> TxResult:
        """submit_and_wait with a retry on transient codes (tef*/tel*/ter*, stale sequence, expired LLS)."""
        for attempt in range(retries + 1):
            try:
                resp = submit_and_wait(tx, self.client, wallet).result
                break
            except XRPLReliableSubmissionException as exc:
                code = _parse_code(str(exc))
                transient = code[:3] in ("tef", "tel", "ter") or "LastLedgerSequence" in str(exc)
                if transient and attempt < retries:
                    time.sleep(2 + 2 * attempt)
                    continue
                return TxResult(False, _parse_hash(str(exc)), code, raw={"error": str(exc)})
        meta = resp.get("meta", {})
        code = meta.get("TransactionResult", "unknown") if isinstance(meta, dict) else "unknown"
        txj = resp.get("tx_json", resp)
        return TxResult(code == "tesSUCCESS", resp.get("hash", txj.get("hash", "")), code,
                        txj.get("Sequence"), txj.get("TicketSequence"), resp.get("ledger_index"), resp)


# --------------------------------------------------------------------------- helpers
def _money(v) -> str:
    d = Decimal(str(v)).quantize(Decimal("0.000001"))
    s = format(d.normalize(), "f")
    return s if s != "-0" else "0"


def _with_ticket(tx: Transaction, ticket: int) -> Transaction:
    d = tx.to_dict()
    d.update(ticket_sequence=ticket, sequence=0)
    return type(tx).from_dict(d)


def _memos(text: Optional[str]):
    if not text:
        return None
    from xrpl.models.transactions import Memo
    return [Memo(memo_data=text.encode("utf-8").hex().upper())]


def _parse_code(msg: str) -> str:
    for token in msg.replace(":", " ").replace(",", " ").split():
        if token[:3] in ("tec", "tef", "tel", "tem", "ter") and len(token) > 3:
            return token.strip("'\"")
    return "tecUNKNOWN"


def _parse_hash(msg: str) -> str:
    for token in msg.split():
        t = token.strip("'\",.")
        if len(t) == 64 and all(c in "0123456789ABCDEFabcdef" for c in t):
            return t.upper()
    return ""


def load_wallets(path: str = "state/wallets.json") -> dict:
    import json
    with open(path) as f:
        data = json.load(f)
    data["_wallets"] = {name: Wallet.from_seed(w["seed"]) for name, w in data["wallets"].items()}
    return data
