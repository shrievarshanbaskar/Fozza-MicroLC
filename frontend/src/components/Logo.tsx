/** MicroLC monogram: rounded primary-blue tile with a white lock over a ledger ripple, plus wordmark. */
export function Monogram({ size = 32 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden className="shrink-0">
      <rect width="32" height="32" rx="8" fill="#2454FF" />
      <path d="M11 15.5V12.5a5 5 0 0 1 10 0v3" stroke="#fff" strokeWidth="2.2" fill="none" strokeLinecap="round" />
      <rect x="8.5" y="15" width="15" height="10" rx="2.5" fill="#fff" />
      <circle cx="16" cy="19.5" r="1.6" fill="#2454FF" />
      <path d="M6 27.5c2.5-1.6 4.5-1.6 7 0s4.5 1.6 7 0 4.5-1.6 6 0" stroke="#fff" strokeWidth="1.4" fill="none" strokeLinecap="round" opacity=".9" />
    </svg>
  );
}

export default function Logo({ size = 32, light = false, wordmark = true }: { size?: number; light?: boolean; wordmark?: boolean }) {
  return (
    <span className="inline-flex items-center gap-2.5 select-none" data-testid="logo">
      <Monogram size={size} />
      {wordmark && <span className={`font-sans font-bold tracking-tight ${light ? "text-ink" : "text-white"}`} style={{ fontSize: size * 0.62 }}>MicroLC</span>}
    </span>
  );
}
