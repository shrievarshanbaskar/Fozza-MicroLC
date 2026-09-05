"use client";
import { ReactNode, useId } from "react";
import { TIPS, TipKey } from "@/lib/copy";

/** Hover + keyboard-focus tooltip with fixed copy from lib/copy.ts. Wrap any element, or use the (i) icon. */
export default function InfoTip({ tip, children, side = "bottom", light = false, className = "" }: {
  tip: TipKey | string; children?: ReactNode; side?: "top" | "bottom"; light?: boolean; className?: string;
}) {
  const id = useId();
  const text = (TIPS as Record<string, string>)[tip] ?? tip;
  return (
    <span className={`group relative inline-flex items-center ${className}`} tabIndex={0} aria-describedby={id} data-testid="infotip">
      {children ?? (
        <span aria-hidden className={`inline-flex h-4 w-4 items-center justify-center rounded-full border text-[10px] font-bold ${light ? "border-ink/20 text-ink/50" : "border-white/20 text-white/40"} cursor-help`}>i</span>
      )}
      <span
        role="tooltip"
        id={id}
        className={`pointer-events-none absolute left-1/2 z-50 w-72 -translate-x-1/2 rounded-btn px-3 py-2 text-xs font-normal normal-case tracking-normal leading-relaxed opacity-0 shadow-standard transition-opacity group-hover:opacity-100 group-focus-within:opacity-100 ${
          side === "bottom" ? "top-full mt-2" : "bottom-full mb-2"
        } ${light ? "bg-ink text-white" : "bg-surface-2 text-white border border-white/10"}`}
      >
        {text}
      </span>
    </span>
  );
}
