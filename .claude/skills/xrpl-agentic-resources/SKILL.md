---
name: xrpl-agentic-resources
description: >
  Load context with a curated set of XRPL AI and agent resources so you can work
  on agentic payments, agent wallets, x402, agent credit, and RLUSD ideas on the
  XRP Ledger. On invocation it runs refresh.sh: git pulls the vendored repos
  (clones if missing), crawls a fresh index of every docs sub-page from the live
  sites (they have no sitemap or llms.txt, so it scrapes the nav), and refreshes
  the xrpl.org llms.txt. TRIGGER when: user invokes /xrpl-agentic-resources or asks to
  load agentic XRPL context, or starts work on XRPL agent wallets, agentic
  payments, x402, agent credit, Open Wallet Standard, or RLUSD agent skills.
license: MIT
metadata:
  author: joel
---

# XRPL Agentic Resources

A context pack for building AI and agent ideas on the XRP Ledger. It vendors the
key repos locally (so they load fast and offline) and catalogs the live docs with
their sub-page URLs so you can fetch exactly what a task needs.

This skill lives at `skills/xrpl-agentic-resources/` in the repo. When installed
for an agent it is symlinked into that agent's skills directory (`.claude/skills`,
`.cursor/skills`, or `.codex/skills`); paths below are relative to the skill
directory, which resolves correctly through the symlink.

## On Invocation: Run refresh.sh First (always)

Run this once at the start of every invocation. It pulls each vendored repo
(clones if missing), crawls a FRESH index of every docs sub-page from the live
site nav, and refreshes the xrpl.org llms.txt snapshot. Idempotent and safe. It
needs git, curl, and network access.

```bash
bash skills/xrpl-agentic-resources/scripts/refresh.sh
```

The vendored repos are cloned on demand into the skill directory (they are
gitignored, not committed), so the first run downloads them. The small curated
snapshots in `resources/` are committed and usable offline immediately.

Why a crawl and not a static list: none of the t54 or claw docs sites expose a
sitemap.xml or llms.txt, so a hardcoded page list would go stale as they add or
remove pages. `refresh.sh` instead scrapes the rendered nav on each run and writes
a current page list to `resources/*-docs-index.txt`. Read those generated index
files for the up-to-date set of URLs, then WebFetch the specific pages you need.

If a crawl returns nothing (site markup changed), refresh.sh keeps the previous
index rather than wiping it, and prints a WARN. If that happens, WebFetch the docs
root directly and extract the nav links to rebuild the list.

## Vendored Repos (cloned by refresh.sh into the skill dir, read directly)

| Path | Source | What it is |
| --- | --- | --- |
| `ows/` | github.com/open-wallet-standard/core | Open Wallet Standard core spec. Wallet interoperability primitives relevant to agent wallets. |
| `rlusd-skills/` | github.com/t54-labs/rlusd-skills | t54's RLUSD agent skills (SKILL.md packs for RLUSD operations agents can invoke). |
| `x402-secure/` | github.com/t54-labs/x402-secure | t54's secure x402 implementation. HTTP 402 pay-per-call settlement with verifiable intent. |
| `xrpl-dev-portal/.claude/skills/xrpl-skills/xrpl-agent-wallet/` | XRPLF/xrpl-dev-portal (sparse) | Official XRPL agent-wallet skill. |
| `xrpl-dev-portal/.claude/skills/xrpl-skills/xrpl-payments/` | XRPLF/xrpl-dev-portal (sparse) | Official XRPL payments skill. |
| `XRPL-Standards/` | XRPLF/XRPL-Standards | The XLS specs. Search it for the canonical spec of any amendment (Credentials XLS-70, PermissionedDomains, PermissionedDEX, TokenEscrow, Batch, MPT XLS-33, and so on). |

Start with the two `xrpl-dev-portal` SKILL.md files for canonical XRPL patterns,
then `x402-secure` and `rlusd-skills` for the t54 agentic stack, then `ows` for
wallet-interoperability design.

## xrpl.org Docs Index (local snapshot)

`resources/xrpl-llms.txt` is the `xrpl.org/llms.txt` index: a flat list of every
xrpl.org doc page with its URL. Use it to find the exact canonical page for a
concept (amendments, transaction types, payment channels, escrow, credentials,
permissioned domains, and so on), then WebFetch that URL for the full content.

## Live XRPL Status Tooling

These are the correctness resources, refreshed each run:

- `resources/xrpl-amendments.json` a snapshot of `xrpscan.com/api/v1/amendments`. Check the `enabled` boolean per amendment to know what is live on mainnet before asserting a feature exists. `enabled: false` means not live (it may still be voting).
- `resources/xrpl-fee-settings.json` a snapshot of the `FeeSettings` ledger object. `ReserveBaseDrops`, `ReserveIncrementDrops`, and `BaseFeeDrops`; divide drops by 1,000,000 for XRP. Cite these live, never hardcode reserves or fees.
- **XLS specs**: `XRPL-Standards/` (vendored above). Read the spec README for any amendment.
- Remember a MainnetPropose date is not a usable-on-mainnet date; an amendment still needs 80 percent validator consensus held for two weeks after proposal.

## Live Docs (fresh index every invocation; fetch pages on demand)

There is no local mirror of these sites. `refresh.sh` regenerates a current page
list for each on every run. Read the matching index file, then WebFetch the pages
a task needs. Tip: many pages also serve raw markdown at the same path with a `.md`
suffix; try that first for a clean parse, fall back to WebFetch on the HTML URL.

| Docs site | What it covers | Fresh index file |
| --- | --- | --- |
| https://www.t54.ai/docs | Pre-execution underwriting of agent-mediated finance; Trustline (risk engine, underwriting, compliance), the products (x402-secure, claw-credit, consumer-finance), the XRPL and RLUSD pages, and research. | `resources/t54-docs-index.txt` |
| https://xrpl-x402.t54.ai/docs | XRPL x402: the HTTP 402 pay-per-call standard on XRPL. Overview, quickstart, xrpl-scheme, verifiable-intent, and merchant and client guides. | `resources/xrpl-x402-docs-index.txt` |
| https://www.claw.credit/docs | Agent credit infrastructure (autonomous payments without pre-funding), Skill-First integration in the Open Claw ecosystem, x402 payments across Base, Solana, and XRPL. | `resources/claw-docs-index.txt` |

To read one, for example `cat skills/xrpl-agentic-resources/resources/xrpl-x402-docs-index.txt`, then WebFetch the specific URLs it lists.

## How to Use This for Agentic XRPL Work

- **Agent wallet design**: read `xrpl-dev-portal .../xrpl-agent-wallet/SKILL.md` and `ows/` for the wallet-standard side.
- **Agent payments and settlement**: `xrpl-dev-portal .../xrpl-payments/SKILL.md`, plus payment-channel and escrow pages from the xrpl.org index.
- **Pay-per-call and machine-to-machine payments (x402)**: `x402-secure/` repo plus the xrpl-x402 docs (overview, xrpl-scheme, verifiable-intent, client and merchant guides).
- **Agent credit and underwriting**: t54 Trustline docs and claw.credit docs.
- **RLUSD agent operations**: `rlusd-skills/` repo and the t54 `/docs/xrpl/rlusd-*` pages.
- Cross-reference every native XRPL claim against `resources/xrpl-llms.txt` and the canonical xrpl.org page, and check live amendment status before asserting a feature is available.

## Install

This skill works in Claude Code, Cursor, and Codex (all read a `SKILL.md` folder).
From the repo root run `bash skills/install.sh` to symlink it into `.claude/skills`,
`.cursor/skills`, and `.codex/skills`, or see `skills/README.md` for manual steps.
