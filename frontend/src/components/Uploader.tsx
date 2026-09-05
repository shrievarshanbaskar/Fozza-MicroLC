"use client";
import { useRef, useState } from "react";
import InfoTip from "./InfoTip";

const SLOTS = [
  { file: "invoice.pdf", label: "Commercial Invoice" },
  { file: "bill_of_lading.pdf", label: "Bill of Lading" },
  { file: "packing_list.pdf", label: "Packing List" },
];
const MAX = 10 * 1024 * 1024;

/** Drag-and-drop three PDFs into labeled slots; files are renamed to the slot they land in. */
export default function Uploader({ onSubmit, busy, disabled, onClose }: { onSubmit: (files: File[]) => Promise<void>; busy: boolean; disabled: boolean; onClose: () => void }) {
  const [files, setFiles] = useState<(File | null)[]>([null, null, null]);
  const [err, setErr] = useState<string | null>(null);
  const inputs = [useRef<HTMLInputElement>(null), useRef<HTMLInputElement>(null), useRef<HTMLInputElement>(null)];

  const accept = (i: number, f: File | undefined) => {
    if (!f) return;
    if (f.type !== "application/pdf" && !f.name.toLowerCase().endsWith(".pdf")) { setErr("PDFs only."); return; }
    if (f.size > MAX) { setErr("Each PDF must be 10 MB or smaller."); return; }
    setErr(null);
    setFiles((cur) => cur.map((c, k) => (k === i ? f : c)));
  };
  const ready = files.every(Boolean);
  const submit = async () => {
    if (!ready) return;
    const renamed = files.map((f, i) => new File([f!], SLOTS[i].file, { type: "application/pdf" }));
    await onSubmit(renamed);
  };
  return (
    <section className="card" data-testid="uploader">
      <header className="card-head">
        <span className="micro text-white/70 flex items-center gap-2">Your Own Trade Documents <InfoTip tip="upload" /></span>
        <button className="btn-ghost !py-1 !text-xs" onClick={onClose} data-testid="uploader-close">Close</button>
      </header>
      <div className="grid grid-cols-3 gap-2 p-3">
        {SLOTS.map((s, i) => (
          <div key={s.file}
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => { e.preventDefault(); accept(i, e.dataTransfer.files[0]); }}
            onClick={() => inputs[i].current?.click()}
            data-testid={`slot-${s.file}`}
            className={`cursor-pointer rounded-btn border-2 border-dashed p-3 text-center text-xs ${files[i] ? "border-success/60 bg-success/10 text-green-100" : "border-white/15 bg-white/[0.02] text-white/60 hover:border-primary/60"}`}>
            <div className="micro opacity-70">{s.label}</div>
            <div className="mt-1 truncate">{files[i] ? files[i]!.name : "Drop PDF or click"}</div>
            <input ref={inputs[i]} type="file" accept="application/pdf" className="hidden" onChange={(e) => accept(i, e.target.files?.[0])} />
          </div>
        ))}
      </div>
      <div className="flex items-center gap-3 px-3 pb-3">
        <button className="btn-primary !py-1.5 !text-xs" disabled={!ready || busy || disabled} onClick={submit} data-testid="upload-btn">{busy ? "Uploading & Examining…" : "Upload & Examine"}</button>
        <span className="text-xs muted">{disabled ? "Create a deal first; documents are checked against its credit terms." : "Exactly three PDFs, 10 MB each. Presets remain the default demo path."}</span>
        {err && <span className="text-xs text-red-300">{err}</span>}
      </div>
    </section>
  );
}
