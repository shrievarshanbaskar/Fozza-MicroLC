"use client";
import { useState } from "react";
import { api, Discrepancy, ParsedDoc } from "@/lib/api";
import InfoTip from "./InfoTip";
import { DOC_LABELS } from "@/lib/copy";

const DOCS: { file: string; key: string; tip: "invoice" | "billOfLading" | "packingList" }[] = [
  { file: "invoice.pdf", key: "invoice", tip: "invoice" },
  { file: "bill_of_lading.pdf", key: "bill_of_lading", tip: "billOfLading" },
  { file: "packing_list.pdf", key: "packing_list", tip: "packingList" },
];

export default function DocumentViewer({ dealId, discrepancies, parsed, tab: tabProp, setTab: setTabProp, mode: modeProp, setMode: setModeProp, expanded = false, onToggleExpand }: {
  dealId: string | null; discrepancies: Discrepancy[]; parsed: Record<string, ParsedDoc | null> | undefined;
  tab?: number; setTab?: (i: number) => void; mode?: "pdf" | "fields"; setMode?: (m: "pdf" | "fields") => void; expanded?: boolean; onToggleExpand?: () => void;
}) {
  const [tabState, setTabState] = useState(0);
  const [modeState, setModeState] = useState<"pdf" | "fields">("pdf");
  const tab = tabProp ?? tabState, setTab = setTabProp ?? setTabState;
  const mode = modeProp ?? modeState, setMode = setModeProp ?? setModeState;
  const doc = DOCS[tab];
  const badges = (key: string) => discrepancies.filter((d) => d.doc.split(",").includes(key)).length;
  const flagged = new Set(discrepancies.filter((d) => d.doc.split(",").includes(doc.key)).map((d) => d.field));
  const fields = parsed?.[doc.key] || null;
  return (
    <section className="card flex flex-col" data-testid="doc-viewer" data-expanded={expanded}>
      <header className="card-head">
        <span className="micro text-white/70 flex items-center gap-2">Presentation <InfoTip tip="presentation" /></span>
        <div className="flex gap-1 items-center">
          {onToggleExpand && <button className="badge border border-white/10 text-white/50 hover:text-white" onClick={onToggleExpand} data-testid="presentation-expand">{expanded ? "Collapse" : "Expand"}</button>}
          <button className={`badge border ${mode === "pdf" ? "border-primary/60 bg-primary/20 text-white" : "border-white/10 text-white/50"}`} onClick={() => setMode("pdf")} data-testid="pdf-toggle">PDF</button>
          <button className={`badge border ${mode === "fields" ? "border-primary/60 bg-primary/20 text-white" : "border-white/10 text-white/50"}`} onClick={() => setMode("fields")} data-testid="fields-toggle">Extracted Fields</button>
        </div>
      </header>
      <div className="flex gap-1 px-3 pt-2">
        {DOCS.map((d, i) => (
          <InfoTip key={d.key} tip={d.tip}>
            <button onClick={() => setTab(i)} data-testid={`doc-tab-${d.key}`}
              className={`relative rounded-t-btn px-3 py-1.5 text-xs border-b-2 ${i === tab ? "border-primary text-white bg-white/5" : "border-transparent text-white/50 hover:text-white/80"}`}>
              {DOC_LABELS[d.key]}
              {badges(d.key) > 0 && (
                <span className="ml-2 inline-flex h-4 min-w-4 items-center justify-center rounded-full bg-error px-1 text-[10px] font-bold text-white" data-testid={`badge-${d.key}`}>{badges(d.key)}</span>
              )}
            </button>
          </InfoTip>
        ))}
      </div>
      <div className={`m-3 rounded-btn bg-ink border border-white/[0.06] overflow-hidden flex flex-col ${expanded ? "min-h-[900px]" : "min-h-[520px] md:min-h-[720px]"}`} data-testid="doc-frame">
        {!dealId ? (
          <div className="flex-1 grid place-items-center muted text-sm">Create a deal to load documents</div>
        ) : mode === "pdf" ? (
          <iframe key={`${dealId}-${doc.file}`} title={DOC_LABELS[doc.key]} src={`${api.docUrl(dealId, doc.file)}#toolbar=0&view=FitH`} className="w-full flex-1 bg-white" />
        ) : (
          <div className="flex-1 p-3 mono [overflow-wrap:anywhere]">
            {!fields ? <div className="muted">Run the examiner to extract fields</div> : (
              <table className="w-full"><tbody>
                {Object.entries(fields).filter(([k]) => !k.startsWith("_")).map(([k, v]) => (
                  <tr key={k} className={flagged.has(k) ? "bg-error/15 text-red-200" : "text-white/80"}>
                    <td className="py-0.5 pr-3 text-white/40">{k}</td><td className="py-0.5 break-all">{String(v ?? "—")}</td>
                  </tr>
                ))}
              </tbody></table>
            )}
          </div>
        )}
      </div>
    </section>
  );
}
