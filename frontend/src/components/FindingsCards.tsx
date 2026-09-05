"use client";
import { useState } from "react";
import { Discrepancy, Env, Evidence, Examination } from "@/lib/api";
import InfoTip from "./InfoTip";
import { titleCase } from "@/lib/copy";

const fmt = (v: unknown) => (v === null || v === undefined ? "—" : typeof v === "object" ? JSON.stringify(v) : String(v));

/** AI Findings Cards: failed rules expanded (rule code → status → explanation → found-vs-expected), passed rules collapsed. */
export default function FindingsCards({ env, examination, discrepancies, evidence }: { env: Env | null; examination: Examination | null; discrepancies: Discrepancy[]; evidence: Evidence[] }) {
  const [showPassed, setShowPassed] = useState(false);
  const rules = env ? Object.entries(env.rules) : [];
  const hit = new Map(discrepancies.map((d) => [d.rule_id, d]));
  const ev = new Map((evidence || []).map((e) => [e.rule_id, e]));
  const passed = rules.filter(([rid]) => !hit.has(rid));
  const total = rules.length || 19;
  return (
    <section className="card flex flex-col" data-testid="checklist">
      <header className="card-head flex-wrap">
        <span className="micro text-white/70 flex items-center gap-2 whitespace-nowrap">Examiner Findings · {total} UCP 600 Rules <InfoTip tip="rules" /></span>
        {examination && (
          <InfoTip tip="examinerChip" side="bottom">
            <span data-testid="k-badge" className={`inline-flex items-center whitespace-nowrap rounded-badge border px-2 py-0.5 text-[11px] font-semibold ${discrepancies.length === 0 ? "border-success/40 bg-success/15 text-green-300" : discrepancies.some((d) => d.severity === "fatal") ? "border-error/40 bg-error/15 text-red-300" : "border-amber-500/40 bg-amber-500/15 text-amber-200"}`}>
              Parsed by {titleCase(examination.parser)}&nbsp;·&nbsp;<span className="font-mono">{examination.elapsed_ms ? `${(examination.elapsed_ms / 1000).toFixed(1)}s` : "—"}</span>&nbsp;·&nbsp;<span className="font-mono">k={discrepancies.length}</span>&nbsp;·&nbsp;{titleCase(examination.verdict)}
            </span>
          </InfoTip>
        )}
      </header>
      <div className="p-3 space-y-2 text-xs [overflow-wrap:anywhere]">
        {!examination ? (
          <div className="space-y-2">{[0, 1, 2].map((i) => <div key={i} className="skeleton h-10" />)}<div className="muted">Documents not examined yet</div></div>
        ) : (
          <>
            {discrepancies.map((d) => {
              const e = ev.get(d.rule_id);
              const fatal = d.severity === "fatal";
              return (
                <article key={d.rule_id} data-testid={`rule-${d.rule_id}`} data-hit="true" className={`rounded-btn border p-3 ${fatal ? "border-error/50 bg-error/10" : "border-amber-500/40 bg-amber-500/10"}`}>
                  <div className="flex items-center gap-2">
                    <span className="mono text-white/60">{d.rule_id}</span>
                    <span className={`inline-flex h-4 w-4 items-center justify-center rounded-badge text-[10px] font-bold ${fatal ? "bg-error text-white" : "bg-amber-400 text-ink"}`}>!</span>
                    <span className="font-semibold text-white">{titleCase(d.code)}</span>
                    <span className={`badge ml-auto ${fatal ? "bg-error/30 text-red-200" : "bg-amber-500/30 text-amber-100"}`}>{fatal ? "Fatal · Refuse" : "Negotiable · 1 Rung"}</span>
                  </div>
                  <p className="mt-1.5 text-white/80">{d.message}</p>
                  <div className="mt-2 grid grid-cols-2 gap-2">
                    <div className="rounded-badge bg-error/15 p-2"><div className="micro text-red-300/80">Found · {d.doc.replace(",", " + ")}.{d.field}</div><div className="mono mt-0.5 text-red-100 break-all">{fmt(d.found)}</div></div>
                    <div className="rounded-badge bg-success/15 p-2"><div className="micro text-green-300/80">Expected</div><div className="mono mt-0.5 text-green-100 break-all">{fmt(d.expected)}</div></div>
                  </div>
                  <div className="mt-1.5 flex items-center gap-2 muted"><span className="mono">{d.article.replace("UCP600-", "UCP 600 Art. ")}</span>{d.checkable && <span className="badge bg-violet-500/20 text-violet-200">Oracle-Checkable</span>}</div>
                  {e && <div className="mt-1.5 rounded-badge bg-violet-500/15 p-2 text-violet-200" data-testid={`evidence-${d.rule_id}`}>[Verify Agent] {e.provider ? `${e.provider} · ` : ""}{e.verdict}: {e.summary}</div>}
                </article>
              );
            })}
            <button onClick={() => setShowPassed((s) => !s)} className="w-full rounded-btn border border-success/30 bg-success/10 px-3 py-2 text-left text-green-200 flex items-center gap-2" data-testid="passed-toggle">
              <span className="inline-flex h-4 w-4 items-center justify-center rounded-badge bg-success text-white text-[10px] font-bold">✓</span>
              <span className="font-semibold">Rules Passed <span className="mono">{passed.length}/{total}</span></span>
              <span className="ml-auto muted">{showPassed ? "Hide" : "Show"}</span>
            </button>
            {showPassed && (
              <ul className="grid grid-cols-2 gap-1">
                {passed.map(([rid, r]) => (
                  <li key={rid} data-testid={`rule-${rid}`} data-hit="false" className="flex items-center gap-2 rounded-badge bg-white/[0.03] px-2 py-1 text-white/60">
                    <span className="mono text-white/40">{rid}</span><span className="truncate">{titleCase(r.code)}</span>
                    <span className="ml-auto mono text-white/30" title={env?.articles[r.article]}>{r.article.replace("UCP600-", "Art. ")}</span>
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
      </div>
    </section>
  );
}
