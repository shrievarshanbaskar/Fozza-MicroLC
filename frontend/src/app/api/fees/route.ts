import { NextResponse } from "next/server";

/**
 * Sum the Fee (drops) of validated XRPL transactions.
 * The public testnet JSON-RPC sends no CORS headers, so the browser cannot call it; this route does the
 * `tx` lookups from the Next.js server instead. Hashes that do not resolve are skipped, never guessed.
 */
const RPC = process.env.XRPL_RPC_URL || process.env.NEXT_PUBLIC_XRPL_RPC || "https://s.altnet.rippletest.net:51234/";
const HASH = /^[0-9A-F]{64}$/i;

export const dynamic = "force-dynamic";

export async function POST(req: Request) {
  let body: unknown = null;
  try { body = await req.json(); } catch { /* empty body */ }
  const raw = (body as { hashes?: unknown } | null)?.hashes;
  const hashes = Array.isArray(raw) ? Array.from(new Set(raw.filter((h): h is string => typeof h === "string" && HASH.test(h)))).slice(0, 64) : [];
  const fees = await Promise.all(hashes.map(async (h) => {
    try {
      const r = await fetch(RPC, {
        method: "POST", headers: { "Content-Type": "application/json" }, cache: "no-store",
        body: JSON.stringify({ method: "tx", params: [{ transaction: h }] }),
      });
      const d = await r.json();
      if (!d?.result?.validated) return null;
      const fee = d.result.tx_json?.Fee ?? d.result.Fee; // api_version 2 nests the tx under tx_json; v1 flattens it
      return fee === undefined || fee === null ? null : Number(fee);
    } catch {
      return null;
    }
  }));
  const found = fees.filter((f): f is number => f !== null && Number.isFinite(f));
  return NextResponse.json({ drops: found.reduce((a, b) => a + b, 0), counted: found.length, requested: hashes.length });
}
