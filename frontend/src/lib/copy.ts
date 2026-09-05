// Fixed tooltip copy. Never generated at runtime; every string here was written by hand.
export const TIPS = {
  rules: "UCP 600 is the ICC's global rulebook that banks use to examine Letter of Credit documents. MicroLC encodes 19 of its document checks as deterministic code — the AI reads the documents, the rules decide.",
  examinerChip: "Which parser read the documents, how long extraction took, k = number of negotiable discrepancies found, and the overall verdict. k caps the discount the buyer can seek.",
  live: "Real Groq-powered buyer and seller agents negotiate right now; every line streams as it happens.",
  mock: "A scripted replay of the same flow in the same event format — for offline demos; no API calls.",
  lock: "The buyer locks the full invoice (100%) plus MicroLC's 1% fee into seven separate escrows on the XRP Ledger. The seller can earn up to 100%; any negotiated discount rungs expire back to the buyer; the 1% releases to the platform on settlement.",
  invoice: "The seller's bill: goods, quantity, unit price, total — checked against the credit amount.",
  billOfLading: "The carrier's receipt proving the goods were loaded on a named vessel by a date — the key shipment evidence.",
  packingList: "The itemized contents of the shipment — quantities must agree with the invoice and B/L.",
  presentation: "A real Letter of Credit is paid against documents, not goods — the examiner cross-checks all three against the agreed terms.",
  deal: "Deal ID · preset · current stage.",
  feed: "Watches XRPL testnet for this deal's transactions; rows appear the moment they validate.",
  verifier: "An agent that buys independent shipment evidence over x402 only when a discrepancy is externally checkable and the disputed value is at least 20x the query price. Spending is capped in code: at most 3 calls and 0.25 RLUSD per deal.",
  referee: "The referee is code, not a model. It rejects any offer whose rungs leave [0, k], whose citations are not real rule ids, or whose accept does not mirror the counterparty. One bounce per actor per round, then the offer is clamped.",
  negotiatedPrice: "Invoice amount minus the negotiated discrepancy adjustment: m rungs of 1% each, where m can never exceed k.",
  stage: "Where this deal is in the six-step flow: Create, Examine, Verify, Lock, Negotiate, Settle.",
  rulesPassed: "Rules that found no problem out of the 19 checks. Discrepancies are the rules that fired.",
  wallets: "Live RLUSD balances of the five testnet wallets used by this demo, read from the ledger.",
  verificationLog: "Every x402 payment the verifier agent made: provider, price paid in RLUSD, settlement hash and the verdict it produced.",
  fees: "MicroLC's fee is the 1% tranche of this credit, released on settlement. XRP network fees are the drops burned by this deal's transactions, read from the ledger.",
  finality: "The most recent validated transactions for this deal, as recorded on XRPL testnet.",
  parties: "The importer (applicant) locks funds; the exporter (beneficiary) presents documents; the referee is code.",
  upload: "Drop exactly three PDFs: Commercial Invoice, Bill of Lading, Packing List (10 MB each). They are checked against the credit terms of the current deal.",
  proofStrip: "Seven escrows: 95% base, five 1% discount rungs, 1% platform fee. Green = released, blue = processing, gray = pending, slate = returned to buyer.",
} as const;

export type TipKey = keyof typeof TIPS;

export const DOC_LABELS: Record<string, string> = {
  invoice: "Commercial Invoice",
  bill_of_lading: "Bill of Lading",
  packing_list: "Packing List",
};

export const STAGES = ["Create", "Examine", "Verify", "Lock", "Negotiate", "Settle"] as const;

export const titleCase = (s: string) => s.replace(/[_-]+/g, " ").replace(/\w\S*/g, (w) => w[0].toUpperCase() + w.slice(1).toLowerCase());
