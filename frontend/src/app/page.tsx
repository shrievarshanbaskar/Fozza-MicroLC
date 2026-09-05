import Link from "next/link";
import { redirect } from "next/navigation";
import Logo from "@/components/Logo";
import { readProofStats } from "@/lib/proofStats";

const REPO = process.env.NEXT_PUBLIC_REPO_URL || "https://github.com/shrievarshanbaskar/Fozza-MicroLC";
const fmtHash = (h: string) => `${h.slice(0, 6)}…${h.slice(-4)}`;
const money = (v: string | number) => Number(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export default function Landing({ searchParams }: { searchParams: { deal?: string } }) {
  if (searchParams?.deal) redirect(`/console?deal=${encodeURIComponent(searchParams.deal)}`); // the console used to live at "/"
  const s = readProofStats();
  const stats: { value: string; label: string; note: string }[] = [];
  if (s.avgExamSeconds) stats.push({ value: `${s.avgExamSeconds.toFixed(1)}s`, label: "Average Examination", note: `Groq extraction + 19 rules, mean of ${s.runs} recorded runs` });
  if (s.x402PaidRlusd !== null) stats.push({ value: `${s.x402PaidRlusd.toFixed(2)} RLUSD`, label: "Paid for Verification", note: `${s.x402Payments} x402 payment${s.x402Payments === 1 ? "" : "s"} settled on XRPL testnet` });
  if (s.negotiationWallSeconds) stats.push({ value: `${s.negotiationWallSeconds.toFixed(1)}s`, label: "Negotiation Wall Time", note: "Verification, agent rounds and referee, measured end to end" });
  stats.push({ value: "19 Rules", label: "UCP 600-Style Engine", note: "Deterministic document checks; the AI reads, the rules decide" });

  return (
    <div className="min-h-screen bg-paper text-ink">
      <header className="sticky top-0 z-40 border-b border-ink/[0.06] bg-paper/80 backdrop-blur-md">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
          <Link href="/"><Logo size={32} light /></Link>
          <nav className="flex gap-8 text-sm font-medium text-ink/70">
            <a href="#how-it-works" className="hover:text-ink">How It Works</a>
            <a href="#security" className="hover:text-ink">Security</a>
          </nav>
        </div>
      </header>

      {/* hero */}
      <section className="mx-auto max-w-6xl px-6 pt-20 pb-16 text-center">
        <span className="inline-block rounded-badge border border-primary/20 bg-primary/5 px-3 py-1 micro text-primary">AI-Native Letter of Credit</span>
        <h1 className="mx-auto mt-6 max-w-4xl font-serif text-5xl leading-[1.05] tracking-tight md:text-7xl">A letter of credit that pays out in minutes, not weeks.</h1>
        <p className="mx-auto mt-6 max-w-2xl text-lg text-ink/70">SME trade finance settled in RLUSD on the XRP Ledger. AI examiners, code-enforced referees, and escrow ladders for shipments between $5k and $50k.</p>
        <div className="mt-8 flex flex-col items-center gap-3">
          <Link href="/console" className="l-btn-primary" data-testid="hero-cta">Open a Demo Credit →</Link>
          <Link href="/console?upload=1" className="text-sm text-ink/60 underline-offset-4 hover:underline" data-testid="hero-upload">…or drop your own trade documents</Link>
        </div>

        {/* console preview card, real values from the archived discrepant run */}
        {s.sample && (
          <div className="mx-auto mt-14 max-w-4xl rounded-card border border-ink/10 bg-ink p-5 text-left text-white shadow-standard" data-testid="hero-preview">
            <div className="flex items-center justify-between gap-3 border-b border-white/10 pb-3">
              <span className="badge border border-white/10 bg-white/5 text-white/80 normal-case tracking-normal text-xs whitespace-nowrap">Deal <span className="font-mono ml-1">{s.sample.dealId.toUpperCase()}</span><span className="hidden sm:inline"> · Discrepant · Settled</span></span>
              <span className="font-mono text-xs text-green-300 whitespace-nowrap">{money(Number(s.sample.lcAmount) * 1.01)} RLUSD</span>
            </div>
            <div className="mt-4 grid gap-3 md:grid-cols-2 text-xs">
              <div className="space-y-1.5">
                <Row tone="violet" tag="Verify Agent · pay">{s.sample.evidence ? <>Paid {s.sample.evidence.price} RLUSD to {s.sample.evidence.provider} over x402 · <span className="font-mono">{fmtHash(s.sample.evidence.txHash)}</span></> : "No verification needed"}</Row>
                {s.sample.evidence && <Row tone="violet" tag="Verify Agent · verify">{s.sample.evidence.verdict}: {s.sample.evidence.summary}</Row>}
                {s.sample.buyerAnchor !== null && <Row tone="sky" tag="Buyer Agent · propose">{s.sample.buyerAnchor} rungs</Row>}
                {s.sample.bounce && <Row tone="red" tag="Code Referee · bounce">rungs outside the evidenced ceiling [0, {s.sample.k}]</Row>}
                <Row tone="green" tag="Seller Agent · accept">{s.sample.m} rungs · demurrage arithmetic beats the discount</Row>
              </div>
              <div>
                <div className="micro text-white/40">Escrow Settlement Ladder</div>
                <div className="mt-2 grid grid-cols-7 gap-1">
                  {["Base", "R1", "R2", "R3", "R4", "R5", "Fee"].map((l, i) => {
                    const released = i === 0 || i === 6 || i <= 5 - s.sample!.m;
                    return <div key={l} className={`rounded-badge border p-1.5 text-center ${released ? "border-success/60 bg-success/20 text-green-100" : "border-slate-500/50 bg-slate-500/20 text-slate-200"}`}><div className="micro opacity-70">{l}</div><div className="text-[10px] font-bold">{released ? "✓" : "↩"}</div></div>;
                  })}
                </div>
                <dl className="mt-3 grid grid-cols-3 gap-2 text-center">
                  <div className="rounded-btn bg-white/5 p-2"><dt className="micro text-white/40">Seller</dt><dd className="font-mono text-green-300">{money(s.sample.seller)}</dd></div>
                  <div className="rounded-btn bg-white/5 p-2"><dt className="micro text-white/40">Fee</dt><dd className="font-mono text-amber-200">{money(s.sample.platform)}</dd></div>
                  <div className="rounded-btn bg-white/5 p-2"><dt className="micro text-white/40">Buyer</dt><dd className="font-mono text-slate-200">{money(s.sample.buyerReturned)}</dd></div>
                </dl>
                <p className="mt-2 text-[11px] text-white/40">RLUSD, from a recorded testnet run · k={s.sample.k}, m={s.sample.m}{s.sample.lockSeconds ? ` · 7 escrows locked in ${s.sample.lockSeconds}s` : ""}</p>
              </div>
            </div>
          </div>
        )}
      </section>

      {/* stats */}
      <section className="mx-auto max-w-6xl px-6 pb-20" data-testid="stats-strip">
        <div className="grid gap-4 md:grid-cols-4">
          {stats.map((st) => (
            <div key={st.label} className="l-card p-6">
              <div className="font-serif text-4xl tracking-tight">{st.value}</div>
              <div className="mt-1 text-sm font-semibold">{st.label}</div>
              <div className="mt-1 text-xs text-ink/50">{st.note}</div>
            </div>
          ))}
        </div>
      </section>

      {/* features */}
      <section className="mx-auto max-w-6xl space-y-20 px-6 pb-20">
        <Feature title="AI Examiner with 19 UCP 600-Style Rules" text="Groq reads each PDF into a typed schema; nineteen deterministic checks compare every field with the credit — quantities, dates, ports, parties, vessel and container. Each finding shows the exact field, the value found, the value expected and the article reference, so nobody argues about what is wrong.">
          <div className="l-card p-5 text-sm">
            <div className="micro text-ink/40">Findings Card</div>
            <div className="mt-2 flex items-center gap-2"><span className="font-mono text-xs text-ink/50">R15</span><span className="inline-flex h-4 w-4 items-center justify-center rounded-badge bg-amber-400 text-ink text-[10px] font-bold">!</span><span className="font-semibold">Late Shipment</span><span className="badge ml-auto bg-amber-100 text-amber-800">Negotiable · 1 Rung</span></div>
            <p className="mt-2 text-ink/70">Shipped 3 day(s) after the latest shipment date</p>
            <div className="mt-3 grid grid-cols-2 gap-2 font-mono text-xs"><div className="rounded-badge bg-red-50 p-2 text-red-800"><div className="micro">Found</div>2026-08-23</div><div className="rounded-badge bg-green-50 p-2 text-green-800"><div className="micro">Expected</div>2026-08-20</div></div>
            <div className="mt-2 font-mono text-[11px] text-ink/40">UCP 600 Art. 20(a)(ii)</div>
          </div>
        </Feature>

        <Feature reverse title="Verifier Agents Pay for Real Facts over x402" text="When a discrepancy can be checked against the real shipment and the disputed value is worth at least twenty times the query price, the verifier agent discovers oracle providers, picks the cheapest one that covers the disputed field, pays per call in RLUSD over x402 and records the signed answer. Spending is capped in code: at most three calls and a quarter of an RLUSD per deal.">
          <div className="l-card p-5 font-mono text-xs">
            <div className="micro text-ink/40 font-sans">Evidence Log</div>
            {s.sample?.evidence ? (
              <div className="mt-2 space-y-1.5 text-ink/80">
                <div><span className="text-violet-700">GET</span> /verify/{s.sample.evidence.provider} → <span className="text-amber-700">402 Payment Required</span></div>
                <div><span className="text-violet-700">PAY</span> {s.sample.evidence.price} RLUSD · <span className="text-ink/60">{fmtHash(s.sample.evidence.txHash)}</span> · settled</div>
                <div><span className="text-violet-700">200</span> telemetry{s.sample.evidence.signature ? ` · signed ${s.sample.evidence.signature.slice(0, 12)}…` : ""}</div>
                <div className="rounded-badge bg-green-50 p-2 text-green-800 font-sans">✓ Independent Evidence Verified · {s.sample.evidence.verdict}</div>
              </div>
            ) : <div className="mt-2 text-ink/50">No recorded verification in the proof archive.</div>}
          </div>
        </Feature>

        <Feature title="Code-Enforced Referees" text="Discrepancies become a discount ladder: at most one 1% rung per evidenced discrepancy, never more. A buyer agent may propose and a seller agent may counter, but a pure-code referee rejects any offer outside the evidenced ceiling, any citation that is not a real rule, and any accept that does not mirror the counterparty. Discounts unlock only on document-evidenced discrepancies, so neither side can extort the other, and no model ever moves money.">
          <div className="l-card p-5 text-sm">
            <div className="micro text-ink/40">Discount Ladder</div>
            <div className="mt-3 grid grid-cols-7 gap-1 text-center text-[11px]">
              {["95%", "1%", "1%", "1%", "1%", "1%", "Fee"].map((l, i) => <div key={i} className={`rounded-badge border p-2 ${i === 0 ? "border-ink/20 bg-ink text-white" : i === 6 ? "border-amber-300 bg-amber-50" : "border-ink/10 bg-paper"}`}>{l}</div>)}
            </div>
            <p className="mt-3 text-ink/70">Base 95% is always the seller&apos;s once documents comply. Each 1% rung is released to the seller or returned to the buyer, decided by <span className="font-mono text-xs">m ≤ k</span>. The 1% fee releases to the platform on settlement.</p>
          </div>
        </Feature>

        <Feature reverse title="Seven-Tranche RLUSD Escrow" text="The buyer locks 101% of the credit in seven separate XLS-85 token escrows on the XRP Ledger, created in a single ledger window with XRPL Tickets. Each is gated by a PREIMAGE-SHA-256 condition; releasing money means publishing the preimage. Whatever is not released returns to the buyer automatically at expiry. Every movement has a public hash.">
          <div className="l-card p-5 text-sm">
            <div className="micro text-ink/40">On-Ledger Proof</div>
            {s.sample?.baseCreateHash ? (
              <div className="mt-2 space-y-2 font-mono text-xs text-ink/80">
                <div className="flex justify-between gap-2"><span>EscrowCreate · base</span><a className="text-primary hover:underline" href={`https://testnet.xrpl.org/transactions/${s.sample.baseCreateHash}`} target="_blank" rel="noreferrer">{fmtHash(s.sample.baseCreateHash)} ↗</a></div>
                {s.sample.feeFinishHash && <div className="flex justify-between gap-2"><span>EscrowFinish · fee</span><a className="text-primary hover:underline" href={`https://testnet.xrpl.org/transactions/${s.sample.feeFinishHash}`} target="_blank" rel="noreferrer">{fmtHash(s.sample.feeFinishHash)} ↗</a></div>}
                <div className="rounded-badge bg-green-50 p-2 font-sans text-green-800">Secured by XRPL Escrow · View on Explorer</div>
              </div>
            ) : <div className="mt-2 text-ink/50">No recorded escrow in the proof archive.</div>}
          </div>
        </Feature>
      </section>

      {/* how it works */}
      <section id="how-it-works" className="border-y border-ink/[0.06] bg-white" data-testid="how-it-works">
        <div className="mx-auto max-w-6xl px-6 py-20">
          <h2 className="font-serif text-4xl tracking-tight">How It Works</h2>
          <ol className="mt-10 grid gap-6 md:grid-cols-3 lg:grid-cols-6">
            {[
              ["Create", "The importer opens a credit and the exporter presents the invoice, bill of lading and packing list."],
              ["Examine", "Groq extracts every field; 19 deterministic rules produce k discrepancies with found-versus-expected."],
              ["Verify", "If a discrepancy is checkable and worth it, the verifier agent pays an oracle over x402 and records signed evidence."],
              ["Lock", "The buyer locks 101% in seven RLUSD escrows on XRPL, created together with Tickets."],
              ["Negotiate", "Buyer and seller agents trade rungs; the code referee bounces anything outside the evidence."],
              ["Settle", "Base, fee and kept rungs release with their preimages; conceded rungs return to the buyer."],
            ].map(([t, d], i) => (
              <li key={t} className="l-card p-5"><div className="micro text-primary">Step {i + 1}</div><div className="mt-1 font-semibold">{t}</div><p className="mt-1 text-sm text-ink/60">{d}</p></li>
            ))}
          </ol>
        </div>
      </section>

      {/* security */}
      <section id="security" className="mx-auto max-w-6xl px-6 py-20">
        <h2 className="font-serif text-4xl tracking-tight">Security</h2>
        <ul className="mt-8 grid gap-4 md:grid-cols-2 text-sm text-ink/80">
          {[
            "Funds are held by XRPL escrow objects, not by MicroLC. The ledger enforces release and expiry.",
            "Releasing a tranche requires publishing the cryptographic preimage of its PREIMAGE-SHA-256 condition.",
            "AI never decides money. The payout is a pure function of one integer m, and m can never exceed the evidenced k.",
            "Agent spending is capped in code: at most three oracle calls and 0.25 RLUSD per deal, with the reason for each purchase recorded.",
            "Every action has an on-chain hash: escrow creation, verification payment, release and return.",
            "If an oracle, facilitator or model fails, the deal proceeds on documents alone and unfinished tranches return to the buyer at expiry.",
          ].map((t) => <li key={t} className="l-card p-4 flex gap-3"><span className="mt-0.5 inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-success/10 text-success text-xs font-bold">✓</span>{t}</li>)}
        </ul>
      </section>

      <footer className="border-t border-ink/[0.06] bg-white">
        <div className="mx-auto grid max-w-6xl gap-10 px-6 py-14 md:grid-cols-3">
          <div><Logo size={28} light /><p className="mt-4 max-w-xs text-sm text-ink/60">AI-native trade finance for the modern SME. Settled in RLUSD on the XRP Ledger.</p></div>
          <div><div className="micro text-ink/40">Platform</div><ul className="mt-3 space-y-2 text-sm"><li><a href="#how-it-works" className="hover:text-primary">How It Works</a></li><li><Link href="/console" className="hover:text-primary">Demo Console</Link></li><li><a href="#security" className="hover:text-primary">Security</a></li></ul></div>
          <div><div className="micro text-ink/40">Resources</div><ul className="mt-3 space-y-2 text-sm"><li><a href={REPO} target="_blank" rel="noreferrer" className="hover:text-primary">GitHub Repository</a></li><li><a href="https://testnet.xrpl.org" target="_blank" rel="noreferrer" className="hover:text-primary">XRPL Explorer</a></li><li><a href="https://iccwbo.org/business-solutions/banking-finance/ucp-600/" target="_blank" rel="noreferrer" className="hover:text-primary">UCP 600 Overview</a></li></ul></div>
        </div>
      </footer>
    </div>
  );
}

function Row({ tone, tag, children }: { tone: "violet" | "sky" | "red" | "green"; tag: string; children: React.ReactNode }) {
  const cls = { violet: "border-violet-500/40 bg-violet-500/10 text-violet-100", sky: "border-sky-500/40 bg-sky-500/10 text-sky-100", red: "border-red-500/60 bg-red-500/15 text-red-100", green: "border-green-500/40 bg-green-500/10 text-green-100" }[tone];
  return <div className={`rounded-btn border px-3 py-1.5 ${cls}`}><div className="micro opacity-80">[{tag}]</div><div className="mt-0.5 break-words">{children}</div></div>;
}

function Feature({ title, text, children, reverse = false }: { title: string; text: string; children: React.ReactNode; reverse?: boolean }) {
  return (
    <div className={`grid items-center gap-10 md:grid-cols-2 ${reverse ? "md:[&>*:first-child]:order-2" : ""}`}>
      <div><h3 className="font-serif text-3xl tracking-tight">{title}</h3><p className="mt-4 text-ink/70">{text}</p></div>
      <div>{children}</div>
    </div>
  );
}
