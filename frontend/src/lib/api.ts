export const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
export const XRPL_RPC = process.env.NEXT_PUBLIC_XRPL_RPC || "https://s.altnet.rippletest.net:51234/";

export type Discrepancy = {
  rule_id: string; code: string; doc: string; field: string; found: unknown; expected: unknown;
  severity: "fatal" | "negotiable"; checkable?: boolean; article: string; article_text?: string; message: string;
};
export type ParsedDoc = Record<string, unknown> & { _parser_fallback?: string };
export type Examination = { k: number; verdict: string; parser: string; discrepancies: Discrepancy[]; fatal: string[]; documents: Record<string, ParsedDoc | null>; elapsed_ms?: number };
export type Tranche = { index: number; name: string; kind: string; pct: string; amount: string; destination: string; status: string; create_hash?: string | null; action_hash?: string | null; action_result?: string | null; offer_sequence?: number | null; cancel_after?: number | null; condition?: string | null };
export type Escrow = { status: string; tranches: Tranche[]; lock_seconds?: number; error?: string };
export type AgentEvent = { ts_ms: number; round: number; actor: string; action: string; rungs: number | null; cited: string[]; rationale: string; latency_ms?: number | null; valid?: boolean };
export type SettlementEvent = { index: number; name: string; kind: string; amount: string; destination: string; action: string; status: string; hash: string | null; result: string | null };
export type Evidence = { rule_id: string; verdict: string; summary: string; provider?: string; tx_hash?: string | null; price_rlusd?: string; signature?: string | null };
export type StreamUpdate = { k: number; route: string; discrepancies: Discrepancy[]; evidence: Evidence[]; verifier?: Verifier | null };
export type StreamMeta = { replay: boolean; mode: string; k?: number };
export type Payout = { m: number; refused: boolean; seller: string; platform: string; buyer_returned: string; locked: string; discount_pct: string; lc_amount?: string };
export type DoneEvent = { agreed_rungs: number | null; payout: Payout; status: string };
export type FeedItem = { ts_ms: number; label: string; hash: string | null; result: string; explorer: string | null; kind?: string; tranche?: number };
export type Verifier = { triggered: boolean; reason?: string; provider?: string | null; mock?: boolean; budget?: { calls: number; spent_rlusd: string; max_calls?: number; max_spend_rlusd?: string } };
export type Negotiation = { mode: string; events: AgentEvent[]; k: number; route: string; discrepancies: Discrepancy[]; agreed_rungs: number | null; payout: Payout | null; status: string; evidence: Evidence[]; verifier?: Verifier | null; refusal_notice?: string | null; wall_seconds?: number };
export type DealState = {
  deal_id: string; preset: string; status: string; lc: Record<string, unknown>; documents: string[]; parties: Record<string, string>;
  examination: Examination | null; escrow: Escrow | null; negotiation: Negotiation | null;
  settlement: { m: number; payout: Payout; events: SettlementEvent[]; mode: string; seconds?: number } | null;
  ledger_feed: FeedItem[]; payout_table: Payout[];
};
export type Env = { network: string; wallets: Record<string, { address: string; explorer: string }>; presets: string[]; rules: Record<string, { code: string; article: string; severity: string; checkable: boolean }>; articles: Record<string, string>; expiry_seconds: number; groq: boolean; models: { small?: string; large?: string } };
export type DealSummary = { deal_id: string; preset: string; status: string; k: number | null };

async function j<T>(r: Response): Promise<T> {
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
}
export const api = {
  env: () => fetch(`${API}/api/env`).then(j<Env>),
  deals: () => fetch(`${API}/api/deals`).then(j<DealSummary[]>),
  balances: () => fetch(`${API}/api/balances`).then(j<Record<string, string>>),
  create: (preset: string) => fetch(`${API}/api/deal/create`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ preset }) }).then(j<DealState>),
  get: (id: string) => fetch(`${API}/api/deal/${id}`).then(j<DealState>),
  examine: (id: string, parser = "auto") => fetch(`${API}/api/deal/${id}/examine?parser=${parser}`, { method: "POST" }).then(j<DealState>),
  lock: (id: string) => fetch(`${API}/api/deal/${id}/lock`, { method: "POST" }).then(j<DealState>),
  sweep: (id: string) => fetch(`${API}/api/deal/${id}/sweep`, { method: "POST" }).then(j<{ swept: SettlementEvent[]; deal: DealState }>),
  feed: (id: string, since = 0) => fetch(`${API}/api/feed?deal=${id}&since=${since}`).then(j<FeedItem[]>),
  upload: (id: string, files: File[]) => {
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f, f.name));
    return fetch(`${API}/api/deal/${id}/documents`, { method: "POST", body: fd }).then(j<{ saved: string[] }>);
  },
  docUrl: (id: string, name: string) => `${API}/api/deal/${id}/documents/${name}`,
  streamUrl: (id: string, mode: "live" | "mock") => `${API}/api/deal/${id}/negotiate/stream?mode=${mode}`,
};
export const explorerTx = (h: string) => `https://testnet.xrpl.org/transactions/${h}`;
export const explorerAccount = (a: string) => `https://testnet.xrpl.org/accounts/${a}`;
export const short = (h?: string | null) => (h ? `${h.slice(0, 6)}…${h.slice(-4)}` : "");
export const rlusd = (v: string | number | null | undefined, digits = 2) =>
  v === null || v === undefined || v === "" ? "—" : Number(v).toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });

/** Read the Fee (drops) of validated transactions straight from the public testnet RPC. */
export async function txFeesDrops(hashes: string[]): Promise<number | null> {
  try {
    const fees = await Promise.all(hashes.map(async (h) => {
      const r = await fetch(XRPL_RPC, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ method: "tx", params: [{ transaction: h }] }) });
      const d = await r.json();
      const fee = d?.result?.tx_json?.Fee ?? d?.result?.Fee;
      return fee ? Number(fee) : 0;
    }));
    return fees.reduce((a, b) => a + b, 0);
  } catch {
    return null;
  }
}
