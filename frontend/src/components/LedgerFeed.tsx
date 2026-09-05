"use client";
import { useEffect, useRef, useState } from "react";
import { Env, FeedItem, api, explorerAccount } from "@/lib/api";
import Hash from "./Hash";
import InfoTip from "./InfoTip";

export default function LedgerFeed({ dealId, env, pushed }: { dealId: string | null; env: Env | null; pushed: FeedItem[] }) {
  const [items, setItems] = useState<FeedItem[]>([]);
  const [live, setLive] = useState(false);
  const since = useRef(0);
  useEffect(() => { setItems([]); since.current = 0; }, [dealId]);
  useEffect(() => {
    if (!dealId) { setLive(false); return; }
    let cancelled = false;
    const tick = async () => {
      try {
        const fresh = await api.feed(dealId, since.current);
        if (cancelled) return;
        setLive(true);
        if (fresh.length) { since.current = fresh[fresh.length - 1].ts_ms; setItems((it) => dedupe([...it, ...fresh])); }
      } catch { if (!cancelled) setLive(false); }
    };
    tick();
    const id = setInterval(tick, 2500);
    return () => { cancelled = true; clearInterval(id); };
  }, [dealId]);
  const all = dedupe([...items, ...pushed]).sort((a, b) => a.ts_ms - b.ts_ms);
  return (
    <section className="card flex flex-col" data-testid="ledger-feed">
      <header className="card-head">
        <span className="micro text-white/70 flex items-center gap-2">
          XRPL Testnet Feed · {env?.network}
          <InfoTip tip="feed"><span data-testid="feed-status" className={`badge ${live ? "bg-success/20 text-green-300" : "bg-white/10 text-white/40"}`}><span className={`mr-1 inline-block h-1.5 w-1.5 rounded-full ${live ? "bg-success animate-pulse" : "bg-white/30"}`} />{live ? "Live" : "Idle"}</span></InfoTip>
        </span>
        <span className="flex gap-2 micro text-white/40">{env && Object.entries(env.wallets).map(([k, w]) => <a key={k} className="hover:text-white/80" href={explorerAccount(w.address)} target="_blank" rel="noreferrer">{k}</a>)}</span>
      </header>
      <ul className="max-h-[360px] overflow-y-auto overflow-x-hidden divide-y divide-white/[0.06] text-xs">
        {all.length === 0 && <li className="p-3 muted">No transactions yet for this deal.</li>}
        {all.map((f, i) => (
          <li key={`${f.hash}-${i}`} className="flex items-center gap-3 px-4 py-1.5" data-testid="feed-item">
            <span className={`h-1.5 w-1.5 rounded-full ${f.result === "tesSUCCESS" ? "bg-success" : "bg-error"}`} />
            <span className="mono text-white/40">{new Date(f.ts_ms).toLocaleTimeString()}</span>
            <span className="text-white/90 min-w-0 truncate">{f.label}</span>
            <span className={`badge ${f.result === "tesSUCCESS" ? "bg-success/20 text-green-300" : "bg-error/20 text-red-200"}`}>{f.result === "tesSUCCESS" ? "Success" : f.result || "Pending"}</span>
            <span className="ml-auto"><Hash value={f.hash} /></span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function dedupe(items: FeedItem[]) {
  const seen = new Set<string>();
  return items.filter((i) => { const k = `${i.hash}-${i.label}`; if (seen.has(k)) return false; seen.add(k); return true; });
}
