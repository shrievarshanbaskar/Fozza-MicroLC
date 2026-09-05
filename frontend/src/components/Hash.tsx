"use client";
import { useState } from "react";
import { explorerTx } from "@/lib/api";

/** Truncated hash (8B72A1…9485) with click-to-copy and an explorer link. */
export default function Hash({ value, className = "", light = false }: { value?: string | null; className?: string; light?: boolean }) {
  const [copied, setCopied] = useState(false);
  if (!value) return <span className={`mono ${light ? "text-ink/40" : "text-white/40"}`}>—</span>;
  const short = `${value.slice(0, 6)}…${value.slice(-4)}`;
  const copy = async (e: React.MouseEvent) => {
    e.stopPropagation();
    try { await navigator.clipboard.writeText(value); setCopied(true); setTimeout(() => setCopied(false), 1200); } catch { /* clipboard blocked */ }
  };
  return (
    <span className={`inline-flex items-center gap-1 mono ${className}`} data-testid="hash">
      <button type="button" onClick={copy} title="Copy hash" className={`rounded-badge px-1 hover:bg-white/10 ${light ? "text-ink hover:bg-ink/5" : "text-white/80"}`}>{copied ? "copied" : short}</button>
      <a href={explorerTx(value)} target="_blank" rel="noreferrer" title="View on XRPL explorer" className="text-primary hover:underline">↗</a>
    </span>
  );
}
