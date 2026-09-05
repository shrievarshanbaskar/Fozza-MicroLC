# Team: Fozza · Product: MicroLC — demo video script

Target length: three to four minutes. One browser tab starting at the landing page (`http://localhost:3000`),
one terminal tab tailing the oracle log. Beat 1 opens with the landing page and the **Open a Demo Credit**
button, which lands on `/console`. Everything shown is live on XRPL testnet; use the MOCK toggle only if the
network is down.

## Beat 0 — the problem (20 s)

> "A letter of credit pays an exporter when the bank finds the shipping documents compliant.
> Examination is manual, slow and binary: pay everything or refuse everything. Small exporters
> cannot afford the fees or the wait. MicroLC makes the examiner an AI, makes the verifier an agent
> that buys evidence, and turns the binary decision into a seven-tranche RLUSD escrow ladder on XRPL."

## Beat 1 — create and examine (30 s)

1. On the landing page, scroll once past the real-run preview card and the four measured stats, then click
   **Open a Demo Credit**. On the console pick preset `Discrepant`, click **New Deal**. Point at the three PDF
   tabs and the stage progress card.
2. Click **Examine Documents**. The findings cards light up: nineteen UCP 600 style rules, two hits
   (quantity inconsistent across documents, shipped after the latest shipment date), `k = 2`.
3. Switch to **Extracted fields** on the packing list: the highlighted `3900` versus the invoice's `4000`.

> "The LLM only reads. Every rule is deterministic Python with a UCP article next to it."

## Beat 2 — verification payment (40 s)

1. Click **Lock 101% on XRPL**. Seven escrows land in one ledger through XRPL Tickets; the ledger
   feed fills with EscrowCreate hashes.
2. LIVE mode, click **Negotiate & Settle**. The violet **VERIFY AGENT** rows appear first:
   `discover` (two providers, different price and coverage), `decide` (cheapest provider that covers
   the disputed field, reason recorded), `pay` (0.05 RLUSD over x402, transaction hash), `verify`
   (oracle confirms the late departure).
3. In the terminal: the oracle log shows `402 Payment Required` followed by `200 OK` on the retry.

> "The agent spends only when the disputed value is at least twenty times the query price, never
> more than three calls or a quarter of an RLUSD per deal. Those caps are code, not prompt."

## Beat 3 — referee bounce (30 s)

1. The buyer's opening offer asks for three rungs. The red **REFEREE · BOUNCE** row rejects it:
   rungs outside the evidenced ceiling `[0, 2]`.
2. The buyer complies with two rungs. The seller shows the demurrage arithmetic
   (`days x USD 150`) and accepts or counters. Latency badges show real model round-trips.

> "No model decides money. The referee is pure code; the payout is a pure function of one integer."

## Beat 4 — ladder settlement (40 s)

1. The escrow settlement ladder flips: base and fee **RELEASED**, the kept rungs **RELEASED**, conceded rungs
   **RETURN_PENDING** then **RETURNED** after expiry (click **Sweep expired** if the timer has passed).
2. Read the payout row: seller, platform fee, returned to buyer. Click a hash to open the explorer.

> "Ninety-eight hundred to the seller, one hundred fee, two hundred back to the buyer.
> Every number is on the ledger."

## Beat 5 — the fraud path (20 s, optional)

Preset `fraudulent`: the container on the packing list differs from the bill of lading. The verifier
pays the oracle, the carrier record contradicts the bill of lading's vessel, `FRAUD_SUSPECTED` is
raised and the presentation is refused. Nothing is released; everything returns to the buyer.

## Close (10 s)

> "MicroLC: an AI-native letter of credit where agents examine, buy evidence, negotiate inside
> hard limits, and settle in RLUSD on XRPL. Team Fozza."
