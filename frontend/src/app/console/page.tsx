"use client";
import Link from "next/link";
import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import Logo from "@/components/Logo";
import InfoTip from "@/components/InfoTip";
import Hash from "@/components/Hash";
import DocumentViewer from "@/components/DocumentViewer";
import FindingsCards from "@/components/FindingsCards";
import NegotiationConsole, { StreamStatus } from "@/components/NegotiationConsole";
import ProofStrip from "@/components/ProofStrip";
import LedgerFeed from "@/components/LedgerFeed";
import VerifierLog from "@/components/VerifierLog";
import Uploader from "@/components/Uploader";
import { AgentEvent, DealState, DealSummary, Discrepancy, Env, Evidence, FeedItem, Payout, SettlementEvent, Verifier, api, explorerAccount, rlusd, txFeesDrops } from "@/lib/api";
import { STAGES, titleCase } from "@/lib/copy";

type View = "deal" | "wallets" | "log";

export default function Page() {
  return <Suspense fallback={<div className="min-h-screen bg-ink p-6 text-white/60">Loading…</div>}><Console /></Suspense>;
}

function Console() {
  const params = useSearchParams();
  const [view, setView] = useState<View>("deal");
  const [env, setEnv] = useState<Env | null>(null);
  const [deal, setDeal] = useState<DealState | null>(null);
  const [preset, setPreset] = useState("discrepant");
  const [mode, setMode] = useState<"live" | "mock">("live");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [liveDisc, setLiveDisc] = useState<Discrepancy[] | null>(null);
  const [evidence, setEvidence] = useState<Evidence[]>([]);
  const [verifier, setVerifier] = useState<Verifier | null>(null);
  const [liveEvents, setLiveEvents] = useState<AgentEvent[]>([]);
  const [settlement, setSettlement] = useState<Record<number, SettlementEvent>>({});
  const [payout, setPayout] = useState<Payout | null>(null);
  const [pushed, setPushed] = useState<FeedItem[]>([]);
  const [streamStatus, setStreamStatus] = useState<StreamStatus>("idle");
  const [showUpload, setShowUpload] = useState(params.get("upload") === "1");
  const [uploadNote, setUploadNote] = useState<string | null>(null);
  const [sidebar, setSidebar] = useState(false);
  const [docTab, setDocTab] = useState(0);
  const [docMode, setDocMode] = useState<"pdf" | "fields">("pdf");
  const [docExpanded, setDocExpanded] = useState(false);
  const bp = useBreakpoint();

  useEffect(() => { api.env().then(setEnv).catch((e) => setError(String(e))); }, []);
  const load = useCallback(async (id: string) => {
    const d = await api.get(id);
    setDeal(d); setPreset(d.preset);
    setLiveDisc(d.negotiation?.discrepancies ?? null); setEvidence(d.negotiation?.evidence ?? []); setVerifier(d.negotiation?.verifier ?? null);
    setLiveEvents(d.negotiation?.events ?? []);
    setPayout(d.settlement?.payout ?? d.negotiation?.payout ?? null);
    setSettlement(Object.fromEntries((d.settlement?.events ?? []).map((e) => [e.index, e])));
  }, []);
  useEffect(() => { const id = params.get("deal"); if (id) load(id).catch((e) => setError(String(e))); }, [params, load]);
  useEffect(() => {
    if (deal?.escrow?.status !== "LOCKING") return;
    const t = setInterval(() => load(deal.deal_id).catch(() => {}), 3000);
    return () => clearInterval(t);
  }, [deal?.escrow?.status, deal?.deal_id, load]);

  const run = async (label: string, fn: () => Promise<unknown>) => {
    setBusy(label); setError(null);
    try { await fn(); } catch (e) { setError(String(e)); } finally { setBusy(null); }
  };
  const resetLocal = () => { setLiveDisc(null); setEvidence([]); setVerifier(null); setLiveEvents([]); setSettlement({}); setPayout(null); setPushed([]); setStreamStatus("idle"); setUploadNote(null); };
  const create = () => run("create", async () => {
    const d = await api.create(preset);
    setDeal(d); resetLocal();
    window.history.replaceState(null, "", `/console?deal=${d.deal_id}`);
  });
  const examine = () => deal && run("examine", async () => setDeal(await api.examine(deal.deal_id, "auto")));
  const lock = () => deal && run("lock", async () => setDeal(await api.lock(deal.deal_id)));
  const sweep = () => deal && run("sweep", async () => { const r = await api.sweep(deal.deal_id); setDeal(r.deal); setSettlement((s) => ({ ...s, ...Object.fromEntries(r.swept.map((e) => [e.index, e])) })); });
  const upload = async (files: File[]) => run("upload", async () => {
    let d = deal;
    if (!d) { d = await api.create(preset); setDeal(d); window.history.replaceState(null, "", `/console?deal=${d.deal_id}`); }
    await api.upload(d.deal_id, files);
    resetLocal();
    const ex = await api.examine(d.deal_id, "auto");
    setDeal(ex);
    const docs = ex.examination?.documents || {};
    const required: Record<string, string[]> = { invoice: ["total_amount", "quantity"], bill_of_lading: ["shipped_on_board_date", "quantity"], packing_list: ["quantity"] };
    const unreadable = Object.entries(required).some(([doc, fields]) => !docs[doc] || fields.some((f) => docs[doc]![f] === null || docs[doc]![f] === undefined));
    setUploadNote(unreadable ? "Couldn't confidently read this document layout; the examiner needs invoice/B-L/packing-list fields. Try the presets or a clearer PDF." : null);
  });

  const discrepancies = liveDisc ?? deal?.examination?.discrepancies ?? [];
  const stage = useMemo(() => {
    if (!deal) return 0;
    if (!deal.examination) return 1;
    if (streamStatus === "streaming") return liveDisc ? 4 : 2;
    if (deal.settlement || streamStatus === "done") return 5;
    if (deal.escrow?.status === "LOCKED") return 4;
    return 3;
  }, [deal, streamStatus, liveDisc]);
  const lcAmount = Number(deal?.lc?.amount ?? 10000);
  const m = payout && !payout.refused ? payout.m : null;
  const negotiated = payout ? (payout.refused ? 0 : lcAmount * (1 - payout.m / 100)) : null;
  const total = env ? Object.keys(env.rules).length : 19;
  const parties = { buyer: String(deal?.lc?.applicant ?? "Importer"), seller: String(deal?.lc?.beneficiary ?? "Exporter") };
  const lockedTotal = deal?.escrow?.tranches?.length ? deal.escrow.tranches.filter((t) => t.status === "LOCKED").reduce((a, t) => a + Number(t.amount), 0) : null;
  const stageAction = () => {
    const newDeal = <button key="new" data-testid="create-btn" className={deal ? "btn-ghost" : "btn-primary"} disabled={busy !== null} onClick={create}>{busy === "create" ? "Creating…" : "New Deal"}</button>;
    if (!deal) return newDeal;
    if (!deal.examination) return <>{newDeal}<button data-testid="examine-btn" className="btn-primary" disabled={busy !== null} onClick={examine}>{busy === "examine" ? "Examining…" : "Examine Documents"}</button></>;
    if (!deal.escrow) return <>{newDeal}<InfoTip tip="lock"><button data-testid="lock-top-btn" className="btn-primary" disabled={busy !== null} onClick={lock}>Lock 101% on XRPL</button></InfoTip></>;
    return newDeal;
  };
  const onSettlement = (s: SettlementEvent) => {
    setSettlement((prev) => ({ ...prev, [s.index]: s }));
    if (s.hash) setPushed((p) => [...p, { ts_ms: Date.now(), label: `Escrow${s.action === "finish" ? "Finish" : "Cancel"} ${s.name} ${s.amount} RLUSD`, hash: s.hash, result: s.result || "", explorer: null }]);
  };

  const panels: Record<string, React.ReactNode> = {
    findings: <FindingsCards key="findings" env={env} examination={deal?.examination ?? null} discrepancies={discrepancies} evidence={evidence} />,
    presentation: <DocumentViewer key="presentation" dealId={deal?.deal_id ?? null} discrepancies={discrepancies} parsed={deal?.examination?.documents}
      tab={docTab} setTab={setDocTab} mode={docMode} setMode={setDocMode} expanded={docExpanded} onToggleExpand={() => setDocExpanded((e) => !e)} />,
    verifier: <VerifierLog key="verifier" events={liveEvents} evidence={evidence} verifier={verifier} streaming={streamStatus === "streaming"} />,
    negotiation: <NegotiationConsole key="negotiation" dealId={deal?.deal_id ?? null} enabled={!!deal?.examination && busy === null} mode={mode} setMode={setMode}
      onEvent={(e) => setLiveEvents((ev) => [...ev, e])}
      onUpdate={(u) => { setLiveDisc(u.discrepancies); setEvidence(u.evidence || []); setVerifier(u.verifier ?? null); }}
      onSettlement={onSettlement}
      onDone={(d) => { setPayout(d.payout); if (deal) load(deal.deal_id).catch(() => {}); }}
      onStatus={(s) => { setStreamStatus(s); if (s === "streaming") setLiveEvents([]); }} />,
    ladder: <ProofStrip key="ladder" escrow={deal?.escrow ?? null} settlement={settlement} payout={payout} lcAmount={lcAmount} onLock={lock} onSweep={sweep} lockEnabled={!!deal?.examination && !deal?.escrow && busy === null} />,
    parties: <PartiesCard key="parties" env={env} parties={parties} />,
    finality: <FinalityCard key="finality" deal={deal} pushed={pushed} />,
    fees: <FeesCard key="fees" deal={deal} lcAmount={lcAmount} pushed={pushed} />,
  };
  // Independent column flows per breakpoint (Change 4). The expanded Presentation is lifted out to a full-width row.
  const columns: { keys: string[]; className: string }[] =
    bp === "xl" ? [
      { keys: ["findings", "presentation"], className: "xl:col-span-5" },
      { keys: ["verifier", "negotiation", "ladder"], className: "xl:col-span-4" },
      { keys: ["parties", "finality", "fees"], className: "xl:col-span-3" },
    ] : bp === "md" ? [
      { keys: ["findings", "presentation", "ladder"], className: "" },
      { keys: ["verifier", "negotiation", "parties", "finality", "fees"], className: "" },
    ] : [
      { keys: ["presentation", "findings", "negotiation", "verifier", "ladder", "parties", "finality", "fees"], className: "" },
    ];

  return (
    <div className="dark min-h-screen bg-ink text-white flex overflow-x-clip">
      {/* sidebar: sticky on desktop, drawer on mobile */}
      <aside className={`fixed inset-y-0 left-0 z-40 w-56 border-r border-white/[0.06] bg-surface/80 backdrop-blur-md p-4 flex flex-col gap-6 transition-transform md:sticky md:top-0 md:h-[100dvh] md:overflow-y-auto md:translate-x-0 md:shrink-0 ${sidebar ? "translate-x-0" : "-translate-x-full"}`} data-testid="sidebar">
        <Link href="/" className="inline-flex"><Logo size={30} /></Link>
        <nav className="flex flex-col gap-1 text-sm">
          {([["deal", "Active Deal"], ["wallets", "RLUSD Wallets"], ["log", "Verification Log"]] as [View, string][]).map(([v, label]) => (
            <button key={v} data-testid={`nav-${v}`} onClick={() => { setView(v); setSidebar(false); }} className={`rounded-btn px-3 py-2 text-left ${view === v ? "bg-primary/20 text-white" : "text-white/60 hover:bg-white/5"}`}>{label}</button>
          ))}
        </nav>
        <div className="mt-auto text-[11px] muted">Team: Fozza · Product: MicroLC<br />XRPL testnet · {env?.network}</div>
      </aside>

      <div className="flex-1 min-w-0 flex flex-col gap-3 pb-6">
        {/* sticky deal header */}
        <div className="sticky top-0 z-30 bg-ink border-b border-white/[0.06] px-3 md:px-4 py-3" data-testid="deal-header">
          <header className="card flex flex-wrap items-center gap-3 px-4 py-2.5">
            <button className="md:hidden btn-ghost !px-2" onClick={() => setSidebar((s) => !s)} aria-label="Menu">☰</button>
            {deal ? (
              <InfoTip tip="deal"><span data-testid="deal-id" className="badge border border-white/10 bg-white/5 text-white/80 normal-case tracking-normal text-xs font-semibold">Deal <span className="mono ml-1">{deal.deal_id.toUpperCase()}</span> · {titleCase(deal.preset)} · {titleCase(deal.status)}</span></InfoTip>
            ) : <span className="text-sm muted">No deal open</span>}
            {deal && <span className="text-sm text-white/80 truncate"><span className="font-semibold text-white">{parties.buyer}</span> <span className="muted">→</span> <span className="font-semibold text-white">{parties.seller}</span></span>}
            {lockedTotal !== null && <span className="mono text-sm text-green-300" data-testid="escrow-balance">{rlusd(lockedTotal)} RLUSD in escrow</span>}
            <span className="flex-1" />
            <select data-testid="preset" value={preset} onChange={(e) => setPreset(e.target.value)} className="rounded-btn border border-white/10 bg-surface px-2.5 py-1.5 text-sm">
              {(env?.presets || ["clean", "discrepant", "fraudulent"]).map((p) => <option key={p} value={p}>{titleCase(p)}</option>)}
            </select>
            <button className="btn-ghost" onClick={() => setShowUpload((s) => !s)} data-testid="upload-toggle">Upload PDFs</button>
            {stageAction()}
          </header>
        </div>
        <div className="flex flex-col gap-3 px-3 md:px-4">
        {error && <div className="rounded-btn border border-error/40 bg-error/10 px-3 py-2 text-xs text-red-200" data-testid="error">{error}</div>}

        {view === "wallets" && <WalletsView env={env} />}
        {view === "log" && <VerificationLogView />}
        {view === "deal" && (
          <>
            {showUpload && <Uploader onSubmit={upload} busy={busy === "upload"} disabled={false} onClose={() => setShowUpload(false)} />}
            {uploadNote && <div className="rounded-btn border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-100" data-testid="upload-note">{uploadNote}</div>}

            {/* stat cards: natural height, not sticky */}
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3" data-testid="stat-cards">
              <StatCard label="Current Stage" tip="stage" value={STAGES[stage]}>
                <div className="mt-2 flex gap-1">{STAGES.map((s, i) => <span key={s} title={s} className={`h-1.5 flex-1 rounded-full ${i < stage ? "bg-success" : i === stage ? "bg-primary animate-pulse" : "bg-white/10"}`} />)}</div>
              </StatCard>
              <StatCard label="Rules Passed" tip="rulesPassed" value={deal?.examination ? <><span className="text-green-300">{total - discrepancies.length}</span><span className="muted">/{total}</span></> : "—"}>
                {deal?.examination && <div className="mt-1 text-xs"><span className="text-red-300 font-semibold">{discrepancies.length}</span> <span className="muted">discrepanc{discrepancies.length === 1 ? "y" : "ies"}{discrepancies.some((d) => d.severity === "fatal") ? " · fatal" : ""}</span></div>}
              </StatCard>
              <StatCard label="Verifier Agent" tip="verifier" value={
                streamStatus === "streaming" && !evidence.length && !verifier ? <span className="text-violet-200 text-base"><span className="mr-2 inline-block h-2 w-2 rounded-full bg-violet-300 animate-ping" />Active</span>
                : verifier?.triggered ? <span className="text-violet-200">{verifier.mock ? "Mock" : "Paid"}</span> : <span className="muted">Idle</span>}>
                <div className="mt-1 text-xs muted truncate">{streamStatus === "streaming" && !evidence.length ? "Sourcing x402 Evidence…" : verifier?.budget ? `${verifier.budget.calls} call · ${verifier.budget.spent_rlusd} RLUSD${verifier.mock ? " (mock)" : ""}` : "Waiting for a checkable discrepancy"}</div>
              </StatCard>
              <StatCard label="Negotiated Price" tip="negotiatedPrice" value={negotiated === null ? <span className="muted">—</span> : <span className="text-green-300">{rlusd(negotiated)} <span className="text-xs muted">RLUSD</span></span>}>
                <div className="mt-1 text-xs">{m ? <span className="text-red-300">−{m}% Discrepancy Adj.</span> : payout?.refused ? <span className="text-red-300">Refused · 0 released</span> : <span className="muted">Invoice {rlusd(lcAmount)} RLUSD</span>}</div>
              </StatCard>
            </div>

            {/* expanded presentation spans the full row; the columns reflow below it */}
            {docExpanded && <div className="w-full" data-testid="presentation-expanded-row">{panels.presentation}</div>}

            {/* main grid: independent column flows, align-items start */}
            <section className={`grid grid-cols-1 gap-3 items-start ${bp === "xl" ? "xl:grid-cols-12" : bp === "md" ? "md:grid-cols-2" : ""}`} data-testid="main-grid">
              {columns.map((col, i) => (
                <div key={i} className={`flex flex-col gap-3 min-w-0 ${col.className}`}>
                  {col.keys.filter((k) => !(docExpanded && k === "presentation")).map((k) => panels[k])}
                </div>
              ))}
            </section>
            <LedgerFeed dealId={deal?.deal_id ?? null} env={env} pushed={pushed} />
          </>
        )}
        </div>
      </div>
    </div>
  );
}

/** xl >= 1280, md >= 768, else sm. Client-only; defaults to xl before hydration. */
function useBreakpoint(): "xl" | "md" | "sm" {
  const [bp, setBp] = useState<"xl" | "md" | "sm">("xl");
  useEffect(() => {
    const xl = window.matchMedia("(min-width: 1280px)");
    const md = window.matchMedia("(min-width: 768px)");
    const update = () => setBp(xl.matches ? "xl" : md.matches ? "md" : "sm");
    update();
    xl.addEventListener("change", update); md.addEventListener("change", update);
    return () => { xl.removeEventListener("change", update); md.removeEventListener("change", update); };
  }, []);
  return bp;
}

function StatCard({ label, tip, value, children }: { label: string; tip: Parameters<typeof InfoTip>[0]["tip"]; value: React.ReactNode; children?: React.ReactNode }) {
  return (
    <div className="card p-4" data-testid={`stat-${label.toLowerCase().replace(/\s+/g, "-")}`}>
      <div className="micro text-white/40 flex items-center gap-2">{label} <InfoTip tip={tip} /></div>
      <div className="mt-1 text-2xl font-semibold font-serif tracking-tight">{value}</div>
      {children}
    </div>
  );
}

function PartiesCard({ env, parties }: { env: Env | null; parties: { buyer: string; seller: string } }) {
  const w = env?.wallets || {};
  const rows = [
    { tag: "IMP", name: parties.buyer, role: "Importer · Applicant", addr: w.buyer?.address },
    { tag: "EXP", name: parties.seller, role: "Exporter · Beneficiary", addr: w.seller?.address },
    { tag: "REF", name: "Code Referee", role: "Pure-code validator · no wallet, no model", addr: undefined },
  ];
  return (
    <section className="card" data-testid="parties">
      <header className="card-head"><span className="micro text-white/70 flex items-center gap-2">Parties <InfoTip tip="parties" /></span></header>
      <ul className="p-3 space-y-2 text-xs">
        {rows.map((r) => (
          <li key={r.tag} className="flex items-start gap-3">
            <span className="badge bg-primary/20 text-blue-200 mt-0.5">{r.tag}</span>
            <div className="min-w-0"><div className="font-semibold text-white truncate">{r.name}</div><div className="muted">{r.role}</div>
              {r.addr && <a className="mono text-primary hover:underline" href={explorerAccount(r.addr)} target="_blank" rel="noreferrer">{r.addr.slice(0, 8)}…{r.addr.slice(-4)} ↗</a>}</div>
          </li>
        ))}
      </ul>
    </section>
  );
}

function FinalityCard({ deal, pushed }: { deal: DealState | null; pushed: FeedItem[] }) {
  const items = [...(deal?.ledger_feed ?? []), ...pushed].filter((f) => f.hash).sort((a, b) => b.ts_ms - a.ts_ms).slice(0, 3);
  return (
    <section className="card" data-testid="finality">
      <header className="card-head"><span className="micro text-white/70 flex items-center gap-2">XRPL Finality <InfoTip tip="finality" /></span></header>
      <ul className="p-3 space-y-2 text-xs">
        {items.length === 0 && <li className="muted">No validated transactions yet.</li>}
        {items.map((f, i) => (
          <li key={`${f.hash}-${i}`} className="flex items-center gap-2">
            <div className="min-w-0 flex-1"><div className="truncate text-white/90">{f.label}</div><Hash value={f.hash} /></div>
            <span className={`badge ${f.result === "tesSUCCESS" ? "bg-success/20 text-green-300" : "bg-error/20 text-red-200"}`}>{f.result === "tesSUCCESS" ? "Success" : f.result}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function FeesCard({ deal, lcAmount, pushed }: { deal: DealState | null; lcAmount: number; pushed: FeedItem[] }) {
  const [drops, setDrops] = useState<number | null | undefined>(undefined);
  const hashes = useMemo(() => Array.from(new Set([...(deal?.ledger_feed ?? []), ...pushed].map((f) => f.hash).filter(Boolean) as string[])), [deal?.ledger_feed, pushed]);
  useEffect(() => { if (!hashes.length) { setDrops(undefined); return; } txFeesDrops(hashes).then(setDrops); }, [hashes]);
  return (
    <section className="card" data-testid="fees">
      <header className="card-head"><span className="micro text-white/70 flex items-center gap-2">Fees <InfoTip tip="fees" /></span></header>
      <dl className="p-3 grid grid-cols-[1fr_auto] gap-y-2 text-xs">
        <dt className="muted">MicroLC platform fee (1%)</dt><dd className="mono text-amber-200">{deal ? `${rlusd(lcAmount * 0.01)} RLUSD` : "—"}</dd>
        <dt className="muted">XRP network fees · {hashes.length} tx</dt>
        <dd className="mono text-white/80">{drops === undefined ? "—" : drops === null ? "unavailable" : `${(drops / 1_000_000).toFixed(6)} XRP`}</dd>
      </dl>
    </section>
  );
}

function WalletsView({ env }: { env: Env | null }) {
  const [bal, setBal] = useState<Record<string, string> | null>(null);
  useEffect(() => { api.balances().then(setBal).catch(() => setBal({})); }, []);
  const roles: Record<string, string> = { issuer: "RLUSD issuer (demo)", buyer: "Importer · locks escrows", seller: "Exporter · receives tranches", platform: "MicroLC · pays oracles, holds fulfillments", oracle: "Oracle · x402 merchant" };
  return (
    <section className="card" data-testid="wallets-view">
      <header className="card-head"><span className="micro text-white/70 flex items-center gap-2">RLUSD Wallets · Testnet <InfoTip tip="wallets" /></span></header>
      <table className="w-full text-sm"><tbody>
        {Object.entries(env?.wallets || {}).map(([k, w]) => (
          <tr key={k} className="border-b border-white/[0.06]">
            <td className="px-4 py-3 font-semibold capitalize">{k}</td>
            <td className="px-4 py-3 muted text-xs">{roles[k]}</td>
            <td className="px-4 py-3"><a className="mono text-primary hover:underline" href={explorerAccount(w.address)} target="_blank" rel="noreferrer">{w.address} ↗</a></td>
            <td className="px-4 py-3 text-right mono text-green-300">{bal === null ? <span className="skeleton inline-block h-4 w-20" /> : k === "issuer" ? <span className="muted">issuer</span> : `${rlusd(bal[k])} RLUSD`}</td>
          </tr>
        ))}
      </tbody></table>
    </section>
  );
}

function VerificationLogView() {
  const [rows, setRows] = useState<{ deal: DealSummary; ev: Evidence }[] | null>(null);
  useEffect(() => {
    (async () => {
      try {
        const deals = (await api.deals()).slice(0, 12);
        const states = await Promise.all(deals.map((d) => api.get(d.deal_id).catch(() => null)));
        const out: { deal: DealSummary; ev: Evidence }[] = [];
        states.forEach((s, i) => (s?.negotiation?.evidence || []).forEach((ev) => out.push({ deal: deals[i], ev })));
        setRows(out);
      } catch { setRows([]); }
    })();
  }, []);
  return (
    <section className="card" data-testid="verification-log-view">
      <header className="card-head"><span className="micro text-white/70 flex items-center gap-2">Verification Log · x402 Evidence <InfoTip tip="verificationLog" /></span></header>
      {rows === null ? <div className="p-4 space-y-2">{[0, 1].map((i) => <div key={i} className="skeleton h-8" />)}</div> : rows.length === 0 ? <div className="p-4 muted text-sm">No paid verifications recorded yet.</div> : (
        <table className="w-full text-xs"><thead><tr className="micro text-white/40 text-left"><th className="px-4 py-2">Deal</th><th className="px-4 py-2">Rule</th><th className="px-4 py-2">Provider</th><th className="px-4 py-2">Price</th><th className="px-4 py-2">Verdict</th><th className="px-4 py-2">Tx</th></tr></thead><tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-t border-white/[0.06]">
              <td className="px-4 py-2 mono">{r.deal.deal_id}</td><td className="px-4 py-2 mono">{r.ev.rule_id}</td><td className="px-4 py-2">{r.ev.provider || "—"}</td>
              <td className="px-4 py-2 mono">{r.ev.price_rlusd ? `${r.ev.price_rlusd} RLUSD` : "—"}</td>
              <td className="px-4 py-2"><span className={`badge ${r.ev.verdict === "CONFIRMS" ? "bg-success/20 text-green-300" : r.ev.verdict === "MISMATCH" ? "bg-error/20 text-red-200" : "bg-white/10 text-white/60"}`}>{r.ev.verdict}</span></td>
              <td className="px-4 py-2"><Hash value={r.ev.tx_hash} /></td>
            </tr>
          ))}
        </tbody></table>
      )}
    </section>
  );
}
