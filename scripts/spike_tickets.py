"""Stretch spike: submit N EscrowCreates in parallel via Tickets vs sequentially; print timings + hashes."""
import json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv; load_dotenv(".env")
from xrpl_escrow import LedgerClient, load_wallets, make_condition

N = int(sys.argv[1]) if len(sys.argv) > 1 else 3
data = load_wallets(); w = data["_wallets"]; issuer = data["wallets"]["issuer"]["address"]
lc = LedgerClient(data["rpc_url"])
out = {"n": N}

t0 = time.time()
seq = [lc.create_escrow(w["buyer"], w["seller"].classic_address, "1", issuer, make_condition()[0], expiry_seconds=120) for _ in range(N)]
out["sequential_seconds"] = round(time.time() - t0, 1)
out["sequential"] = [r.to_dict() for r in seq]

t0 = time.time()
specs = [{"destination": w["seller"].classic_address, "value": "1", "condition": make_condition()[0], "memo": f"ticket-spike-{i}"} for i in range(N)]
par = lc.create_escrows_parallel(w["buyer"], specs, issuer, expiry_seconds=120)
out["tickets_seconds_incl_ticketcreate"] = round(time.time() - t0, 1)
out["tickets"] = [r.to_dict() for r in par]
out["all_ok"] = all(r.ok for r in seq + par)
print(json.dumps(out, indent=2))
Path("proof").mkdir(exist_ok=True)
Path("proof/tickets_spike.json").write_text(json.dumps(out, indent=2))
