#!/usr/bin/env bash
# Refresh all xrpl-agentic-resources on demand.
#   1. git pull each vendored repo (clone if missing)
#   2. regenerate a FRESH index of every docs sub-page by crawling the live nav
#      (these sites expose no sitemap.xml or llms.txt, so we scrape rendered links)
#   3. refresh the xrpl.org llms.txt snapshot
# Safe to run every invocation. Idempotent.
set -u
export PATH=/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}

S="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$S/resources"
mkdir -p "$OUT"

echo "== repos =="
refresh_repo () {  # $1 = subdir, $2 = remote
  if [ -d "$S/$1/.git" ]; then
    echo "pull $1"; git -C "$S/$1" pull --ff-only 2>&1 | tail -1
  else
    echo "clone $1"; git clone --depth 1 "$2" "$S/$1" 2>&1 | tail -1
  fi
}
refresh_repo ows          https://github.com/open-wallet-standard/core.git
refresh_repo rlusd-skills https://github.com/t54-labs/rlusd-skills
refresh_repo x402-secure  https://github.com/t54-labs/x402-secure

if [ -d "$S/xrpl-dev-portal/.git" ]; then
  echo "pull xrpl-dev-portal"; git -C "$S/xrpl-dev-portal" pull --ff-only 2>&1 | tail -1
else
  echo "clone xrpl-dev-portal (sparse)"
  git clone --depth 1 --filter=blob:none --sparse https://github.com/XRPLF/xrpl-dev-portal.git "$S/xrpl-dev-portal" 2>&1 | tail -1
  git -C "$S/xrpl-dev-portal" sparse-checkout set \
    .claude/skills/xrpl-skills/xrpl-agent-wallet \
    .claude/skills/xrpl-skills/xrpl-payments 2>&1 | tail -1
fi

# XRPL-Standards (XLS specs). Cloned into the skill directory so this pack is
# self-contained and portable on any machine.
STD="$S/XRPL-Standards"
if [ -d "$STD/.git" ]; then
  echo "pull XRPL-Standards"; git -C "$STD" pull --ff-only 2>&1 | tail -1
else
  echo "clone XRPL-Standards"; git clone --depth 1 https://github.com/XRPLF/XRPL-Standards.git "$STD" 2>&1 | tail -1
fi

echo "== live XRPL status (from /devrel-review + /xls) =="
# Live amendment status (enabled/voting) and network reserves/fees. Snapshot each
# run so agentic work always cites current mainnet state.
if curl -s https://xrpscan.com/api/v1/amendments -o "$OUT/xrpl-amendments.json" && [ -s "$OUT/xrpl-amendments.json" ]; then
  echo "amendments -> xrpl-amendments.json"
else echo "WARN: amendments fetch failed (kept previous)"; fi
if curl -s https://xrpscan.com/api/v1/object/FeeSettings -o "$OUT/xrpl-fee-settings.json" && [ -s "$OUT/xrpl-fee-settings.json" ]; then
  echo "FeeSettings -> xrpl-fee-settings.json"
else echo "WARN: FeeSettings fetch failed (kept previous)"; fi

echo "== live docs index (fresh crawl) =="
crawl () {  # $1 = origin, $2 = docs path, $3 = outfile
  local origin="$1" docpath="$2" out="$3"
  curl -sL "$origin$docpath" \
    | grep -oE '/docs/[a-zA-Z0-9_/-]+' \
    | grep -vE '/docs/(layout|page)-[0-9a-f]+' \
    | sort -u \
    | sed "s#^#$origin#" > "$out.tmp" 2>/dev/null
  if [ -s "$out.tmp" ]; then
    mv "$out.tmp" "$out"; echo "$(grep -c . "$out") pages -> ${out##*/}"
  else
    rm -f "$out.tmp"; echo "WARN: no pages from $origin$docpath (kept previous index if any)"
  fi
}
crawl "https://www.t54.ai"       "/docs" "$OUT/t54-docs-index.txt"
crawl "https://xrpl-x402.t54.ai" "/docs" "$OUT/xrpl-x402-docs-index.txt"
crawl "https://www.claw.credit"  "/docs" "$OUT/claw-docs-index.txt"

echo "== xrpl.org llms.txt =="
if curl -s https://xrpl.org/llms.txt -o "$OUT/xrpl-llms.txt" && [ -s "$OUT/xrpl-llms.txt" ]; then
  echo "$(grep -c . "$OUT/xrpl-llms.txt") lines -> xrpl-llms.txt"
else
  echo "WARN: llms.txt fetch failed (kept previous)"
fi

echo "== done. indexes in $OUT =="
