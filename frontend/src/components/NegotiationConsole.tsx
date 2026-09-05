"use client";
import { useEffect, useRef, useState } from "react";
import { AgentEvent, DoneEvent, SettlementEvent, StreamMeta, StreamUpdate, api } from "@/lib/api";
import InfoTip from "./InfoTip";

const STYLE: Record<string, string> = {
  buyer: "border-sky-500/40 bg-sky-500/10 text-sky-100",
  seller: "border-success/40 bg-success/10 text-green-100",
  referee: "border-amber-500/40 bg-amber-500/10 text-amber-100",
  verifier: "border-violet-500/40 bg-violet-500/10 text-violet-100",
  system: "border-white/10 bg-white/5 text-white/70",
};
const LABEL: Record<string, string> = { buyer: "Buyer Agent", seller: "Seller Agent", referee: "Code Referee", verifier: "Verify Agent", system: "System" };
const REVEAL_MS = 300;

export type StreamStatus = "idle" | "streaming" | "done" | "error";

export default function NegotiationConsole({ dealId, enabled, disabledReason = null, mode, setMode, onUpdate, onSettlement, onDone, onStatus, onEvent }: {
  dealId: string | null; enabled: boolean; disabledReason?: string | null; mode: "live" | "mock"; setMode: (m: "live" | "mock") => void;
  onUpdate: (u: StreamUpdate) => void; onSettlement: (s: SettlementEvent) => void; onDone: (d: DoneEvent) => void; onStatus: (s: StreamStatus) => void;
  onEvent?: (e: AgentEvent) => void;
}) {
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [status, setStatus] = useState<StreamStatus>("idle");
  const [meta, setMeta] = useState<StreamMeta | null>(null);
  const queue = useRef<AgentEvent[]>([]);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  const list = useRef<HTMLDivElement>(null);
  const pinned = useRef(true);
  const es = useRef<EventSource | null>(null);

  useEffect(() => () => { es.current?.close(); if (timer.current) clearInterval(timer.current); }, []);
  // auto-scroll only while the reader is already pinned to the newest entry
  useEffect(() => { const el = list.current; if (el && pinned.current) el.scrollTop = el.scrollHeight; }, [events]);
  const onScroll = () => { const el = list.current; if (el) pinned.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40; };
  useEffect(() => { setEvents([]); setStatus("idle"); setMeta(null); queue.current = []; }, [dealId]);

  const start = () => {
    if (!dealId) return;
    es.current?.close();
    setEvents([]); queue.current = []; setStatus("streaming"); onStatus("streaming");
    const src = new EventSource(api.streamUrl(dealId, mode));
    es.current = src;
    const pending: { settlement: SettlementEvent[]; done: DoneEvent | null; update: StreamUpdate | null } = { settlement: [], done: null, update: null };
    if (timer.current) clearInterval(timer.current);
    timer.current = setInterval(() => {
      const next = queue.current.shift();
      if (next) { setEvents((e) => [...e, next]); onEvent?.(next); return; }
      if (pending.update) { onUpdate(pending.update); pending.update = null; }
      if (pending.settlement.length) { onSettlement(pending.settlement.shift()!); return; }
      if (pending.done) { onDone(pending.done); setStatus("done"); onStatus("done"); pending.done = null; if (timer.current) clearInterval(timer.current); }
    }, REVEAL_MS);
    src.addEventListener("meta", (e) => setMeta(JSON.parse((e as MessageEvent).data)));
    src.addEventListener("agent", (e) => { queue.current.push(JSON.parse((e as MessageEvent).data)); });
    src.addEventListener("update", (e) => { pending.update = JSON.parse((e as MessageEvent).data); });
    src.addEventListener("settlement", (e) => { pending.settlement.push(JSON.parse((e as MessageEvent).data)); });
    src.addEventListener("done", (e) => { pending.done = JSON.parse((e as MessageEvent).data); src.close(); });
    src.onerror = () => { src.close(); if (!pending.done) { setStatus("error"); onStatus("error"); } };
  };

  let prev: number | null = null;
  return (
    <section className="card flex flex-col" data-testid="negotiation-console">
      <header className="card-head">
        <span className="micro text-white/70 flex items-center gap-2">Negotiation Console
          {meta && <span className="badge bg-white/10 text-white/60">{meta.replay ? "Replay" : meta.mode}</span>}
          {status === "streaming" && <span className="h-2 w-2 rounded-full bg-success animate-pulse" />}
          <InfoTip tip="referee" />
        </span>
        <div className="flex items-center gap-2">
          <div className="flex rounded-btn border border-white/10 text-[11px] overflow-hidden" data-testid="mode-toggle">
            <InfoTip tip="live"><button data-testid="mode-live" className={`px-2.5 py-1 font-bold tracking-wider ${mode === "live" ? "bg-success/30 text-green-100" : "text-white/50"}`} onClick={() => setMode("live")}>LIVE</button></InfoTip>
            <InfoTip tip="mock"><button data-testid="mode-mock" className={`px-2.5 py-1 font-bold tracking-wider ${mode === "mock" ? "bg-amber-500/30 text-amber-100" : "text-white/50"}`} onClick={() => setMode("mock")}>MOCK</button></InfoTip>
          </div>
          {(() => {
            const btn = (
              <button data-testid="negotiate-btn" disabled={!enabled || status === "streaming"} onClick={start} className="btn-primary !py-1.5 !text-xs"
                title={!enabled && disabledReason ? disabledReason : undefined}>
                {status === "streaming" ? "Running…" : status === "done" ? "Replay" : "Negotiate & Settle"}
              </button>
            );
            // the guard explains itself on hover and focus: money must be on the ledger before agents talk about it
            return !enabled && disabledReason ? <InfoTip tip={disabledReason === "Lock the escrow ladder first" ? "negotiateLocked" : disabledReason}>{btn}</InfoTip> : btn;
          })()}
        </div>
      </header>
      <div ref={list} onScroll={onScroll} className="max-h-[460px] overflow-y-auto overflow-x-hidden p-3 space-y-1.5 text-xs" data-testid="event-list">
        {events.length === 0 && (
          status === "streaming" ? <div className="space-y-2">{[0, 1, 2].map((i) => <div key={i} className="skeleton h-9" />)}</div>
          : <div className="p-4 muted" data-testid="negotiation-placeholder">{enabled ? "Ready. Agents negotiate the discount ladder; the referee is code." : disabledReason ?? "Examine the documents first."}</div>
        )}
        {events.map((e, i) => {
          const latency = e.latency_ms ?? (prev !== null ? e.ts_ms - prev : null);
          prev = e.ts_ms;
          const bounce = e.action === "bounce";
          const cls = bounce ? "border-error/70 bg-error/15 text-red-100" : STYLE[e.actor] || STYLE.system;
          return (
            <div key={i} data-testid="event" data-actor={e.actor} data-action={e.action} className={`rounded-btn border px-3 py-2 min-w-0 ${cls}`}>
              <div className="flex flex-wrap items-center gap-2 micro opacity-80">
                <span>[{bounce ? "Code Referee · Bounce" : LABEL[e.actor] || e.actor}]</span>
                <span>{e.action}</span>
                {e.round > 0 && <span>Round {e.round}</span>}
                {e.rungs !== null && e.rungs !== undefined && <span className="rounded-badge bg-black/30 px-1 normal-case tracking-normal font-mono">{e.rungs} rung{e.rungs === 1 ? "" : "s"}</span>}
                {e.cited?.length > 0 && <span className="normal-case tracking-normal font-mono [overflow-wrap:anywhere] min-w-0">{e.cited.join(" ")}</span>}
                {latency !== null && latency !== undefined && i > 0 && <span className="ml-auto shrink-0 whitespace-nowrap rounded-badge bg-black/30 px-1 normal-case tracking-normal font-mono" data-testid="latency">{latency} ms</span>}
              </div>
              <div className="mt-1 leading-snug [overflow-wrap:anywhere]">{e.rationale}</div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
