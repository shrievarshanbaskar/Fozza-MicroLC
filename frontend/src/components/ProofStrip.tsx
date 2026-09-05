"use client";
import { useEffect, useState } from "react";
import { Escrow, Payout, SettlementEvent, rlusd } from "@/lib/api";
import Hash from "./Hash";
import InfoTip from "./InfoTip";

const PLAN = [
  { index: 0, name: "base", label: "Base", pct: 0.95, destination: "Seller" },
  { index: 1, name: "rung_1", label: "Rung 1", pct: 0.01, destination: "Seller" },
  { index: 2, name: "rung_2", label: "Rung 2", pct: 0.01, destination: "Seller" },
  { index: 3, name: "rung_3", label: "Rung 3", pct: 0.01, destination: "Seller" },
  { index: 4, name: "rung_4", label: "Rung 4", pct: 0.01, destination: "Seller" },
  { index: 5, name: "rung_5", label: "Rung 5", pct: 0.01, destination: "Seller" },
  { index: 6, name: "fee", label: "Fee", pct: 0.01, destination: "Platform" },
];
const RIPPLE_EPOCH = 946_684_800;

type Seg = "released" | "processing" | "pending" | "returned" | "failed" | "notlocked";
/** onLedger: this tranche's escrow exists (or existed) on XRPL. A PLANNED_* status without it is a plan, not money. */
function segment(status: string, onLedger: boolean): Seg {
  if (status.startsWith("PLANNED_") && !onLedger) return "notlocked";
  if (status === "RELEASED" || status === "PLANNED_RELEASE") return "released";
  if (status === "LOCKING" || status === "RETURN_PENDING") return "processing";
  if (status === "RETURNED" || status === "PLANNED_RETURN") return "returned";
  if (status === "FAILED") return "failed";
  return "pending";
}
const SEG_STYLE: Record<Seg, string> = {
  released: "border-success/60 bg-success/20 text-green-100",
  processing: "border-primary/60 bg-primary/20 text-blue-100",
  pending: "border-white/10 bg-white/5 text-white/50",
  returned: "border-slate-500/50 bg-slate-500/20 text-slate-200",
  failed: "border-error/60 bg-error/20 text-red-100",
  notlocked: "border-dashed border-white/15 bg-white/[0.03] text-white/40",
};
const SEG_LABEL: Record<Seg, string> = { released: "✓ Released", processing: "● Processing", pending: "Pending", returned: "↩ Returned", failed: "✕ Failed", notlocked: "Not locked" };

export default function ProofStrip({ escrow, settlement, payout, lcAmount, onLock, onSweep, lockEnabled }: {
  escrow: Escrow | null; settlement: Record<number, SettlementEvent>; payout: Payout | null; lcAmount: number; onLock: () => void; onSweep: () => void; lockEnabled: boolean;
}) {
  const [now, setNow] = useState(Math.floor(Date.now() / 1000));
  useEffect(() => { const t = setInterval(() => setNow(Math.floor(Date.now() / 1000)), 1000); return () => clearInterval(t); }, []);
  const rows = PLAN.map((p) => {
    const t = escrow?.tranches?.find((x) => x.index === p.index);
    const s = settlement[p.index];
    const status = s?.status || t?.status || (escrow?.status === "LOCKING" ? "LOCKING" : "PLANNED");
    const amount = t?.amount ?? (lcAmount * p.pct).toFixed(2);
    const onLedger = !!t?.create_hash && t.status !== "FAILED";
    const seg = segment(status, onLedger);
    const remaining = t?.cancel_after ? t.cancel_after + RIPPLE_EPOCH - now : null;
    return { ...p, t, s, status, amount, seg, hash: s?.hash || t?.action_hash || t?.create_hash, remaining };
  });
  const pending = rows.filter((r) => r.status === "RETURN_PENDING").length;
  const locked = !!escrow?.tranches?.length && escrow.status !== "LOCKING" && escrow.status !== "FAILED";
  const everLocked = !!escrow?.tranches?.some((t) => t.create_hash && t.status !== "FAILED"); // money actually reached the ledger
  const money = (v: string) => (everLocked ? `${rlusd(v)} RLUSD` : "—");
  return (
    <section className="card flex flex-col" data-testid="tranche-panel">
      <header className="card-head">
        <span className="micro text-white/70 flex items-center gap-2">Escrow Settlement Ladder · 7 XLS-85 Tranches <InfoTip tip="proofStrip" /></span>
        <div className="flex gap-2 items-center">
          {pending > 0 && <button className="btn-ghost !py-1 !text-xs" onClick={onSweep} data-testid="sweep-btn">Sweep {pending} Expired</button>}
          <InfoTip tip="lock">
            <button className="btn-primary !py-1.5 !text-xs" disabled={!lockEnabled} onClick={onLock} data-testid="lock-btn">
              {escrow?.status === "LOCKING" ? "Locking…" : locked ? `Locked · ${escrow?.lock_seconds ?? "—"}s` : "Lock 101% on XRPL"}
            </button>
          </InfoTip>
        </div>
      </header>
      <div className="grid grid-cols-4 sm:grid-cols-7 gap-1.5 p-3 pb-2">
        {rows.map((r) => (
          <div key={r.index} className="group relative">
            <div data-testid={`tranche-${r.name}`} data-status={r.status} className={`rounded-btn border p-2 text-center transition-colors ${SEG_STYLE[r.seg]} ${r.seg === "processing" ? "animate-pulse" : ""}`}>
              <div className="micro opacity-70">{r.label}</div>
              <div className="mono font-semibold text-sm">{rlusd(r.amount, 0)}</div>
              <div className="text-[10px] opacity-70 leading-tight">{Math.round(r.pct * 100)}% → {r.destination}</div>
              <div className="mt-1 text-[10px] font-bold leading-tight">{SEG_LABEL[r.seg]}</div>
            </div>
            {/* rich hover card */}
            <div role="tooltip" className="pointer-events-none absolute left-1/2 bottom-full z-40 mb-2 w-64 -translate-x-1/2 rounded-btn border border-white/10 bg-surface-2 p-3 text-left text-xs text-white opacity-0 shadow-standard group-hover:opacity-100 group-hover:pointer-events-auto">
              <div className="font-semibold">{r.label} · <span className="mono">{rlusd(r.amount)} RLUSD</span></div>
              <dl className="mt-1.5 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-white/70">
                <dt>Destination</dt><dd className="text-white">{r.seg === "returned" ? "Returns to Buyer" : r.destination}</dd>
                <dt>Status</dt><dd className="text-white">{r.status.replaceAll("_", " ")}</dd>
                <dt>Condition</dt><dd className="mono text-white">PREIMAGE-SHA-256</dd>
                <dt>CancelAfter</dt><dd className="mono text-white">{r.remaining === null ? "—" : r.remaining > 0 ? `${r.remaining}s remaining` : "expired"}</dd>
                <dt>Tx</dt><dd><Hash value={r.hash} /></dd>
              </dl>
            </div>
          </div>
        ))}
      </div>
      {payout && (
        <div className="mx-3 mb-3 grid grid-cols-2 sm:grid-cols-4 gap-1.5 text-center text-[11px]" data-testid="payout">
          <Stat label="m · Rungs Conceded" value={payout.refused ? "Refused" : String(payout.m)} />
          <Stat label="Seller Receives" value={money(payout.seller)} tone={everLocked ? "text-green-300" : "text-white/40"} />
          <Stat label="Platform Fee" value={money(payout.platform)} tone={everLocked ? "text-amber-200" : "text-white/40"} />
          <Stat label="Returned to Buyer" value={money(payout.buyer_returned)} tone={everLocked ? "text-slate-200" : "text-white/40"} />
        </div>
      )}
      {escrow?.error && <div className="mx-3 mb-3 rounded-btn border border-error/40 bg-error/10 p-2 text-xs text-red-200">{escrow.error}</div>}
    </section>
  );
}

function Stat({ label, value, tone = "text-white" }: { label: string; value: string; tone?: string }) {
  return <div className="rounded-btn border border-white/[0.06] bg-white/[0.03] p-2"><div className="micro text-white/40">{label}</div><div className={`mono font-semibold ${tone}`}>{value}</div></div>;
}
