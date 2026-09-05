"""API tests (offline): create -> examine (template parser) -> mock negotiation SSE -> plan-only settlement."""
import json
import os
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

os.environ.pop("GROQ_API_KEY", None)  # force template parser + mock agents in this process
import main  # noqa: E402


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("state")
    main.STATE, main.DEALS = tmp, tmp / "deals"
    yield TestClient(main.app)
    shutil.rmtree(tmp, ignore_errors=True)


def parse_sse(text: str):
    events = []
    for block in text.strip().split("\n\n"):
        ev, data = None, None
        for line in block.splitlines():
            if line.startswith("event: "):
                ev = line[7:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])
        if ev:
            events.append((ev, data))
    return events


def test_env_and_create(client):
    assert client.get("/api/env").json()["presets"] == ["clean", "discrepant", "fraudulent"]
    r = client.post("/api/deal/create", json={"preset": "discrepant"})
    assert r.status_code == 200
    st = r.json()
    assert st["status"] == "CREATED" and st["lc"]["lc_number"] == "MLC-SG-2026-0142"
    assert client.get(f"/api/deal/{st['deal_id']}/documents/invoice.pdf").headers["content-type"] == "application/pdf"


def test_examine_and_mock_negotiation_stream(client):
    deal_id = client.post("/api/deal/create", json={"preset": "discrepant"}).json()["deal_id"]
    st = client.post(f"/api/deal/{deal_id}/examine", params={"parser": "template"}).json()
    assert st["examination"]["k"] == 2 and st["status"] == "EXAMINED"
    r = client.get(f"/api/deal/{deal_id}/negotiate/stream", params={"mode": "mock"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(r.text)
    kinds = [k for k, _ in events]
    assert kinds[0] == "meta" and kinds[-1] == "done"
    agents = [d for k, d in events if k == "agent"]
    assert any(a["actor"] == "verifier" and a["action"] == "pay" for a in agents)  # verify beat
    assert any(a["actor"] == "referee" and a["action"] == "bounce" for a in agents)  # bounce beat
    assert {"ts_ms", "round", "actor", "action", "rungs", "cited", "rationale"} <= set(agents[0])
    settlement = [d for k, d in events if k == "settlement"]
    assert len(settlement) == 7 and all(s["status"].startswith("PLANNED_") for s in settlement)
    done = events[-1][1]
    assert done["status"] == "CLOSED" and 0 <= done["agreed_rungs"] <= 2
    assert done["payout"]["seller"] in ("9800", "9900", "10000")
    # replay from persisted state, no re-run
    r2 = client.get(f"/api/deal/{deal_id}/negotiate/stream", params={"mode": "mock"})
    ev2 = parse_sse(r2.text)
    assert ev2[0][1]["replay"] is True and [k for k, _ in ev2].count("agent") == len(agents)
    assert client.get(f"/api/deal/{deal_id}").json()["status"] == "NEGOTIATED"


def test_clean_and_fraud_paths(client):
    clean = client.post("/api/deal/create", json={"preset": "clean"}).json()["deal_id"]
    client.post(f"/api/deal/{clean}/examine", params={"parser": "template"})
    done = parse_sse(client.get(f"/api/deal/{clean}/negotiate/stream", params={"mode": "mock"}).text)[-1][1]
    assert done["agreed_rungs"] == 0 and done["payout"]["seller"] == "10000"
    fraud = client.post("/api/deal/create", json={"preset": "fraudulent"}).json()["deal_id"]
    client.post(f"/api/deal/{fraud}/examine", params={"parser": "template"})
    ev = parse_sse(client.get(f"/api/deal/{fraud}/negotiate/stream", params={"mode": "mock"}).text)
    # mock verifier confirms (no fraud); container mismatch stays negotiable with k=1
    assert ev[-1][1]["status"] == "CLOSED" and ev[-1][1]["agreed_rungs"] <= 1


def test_manual_settle_and_feed(client):
    deal_id = client.post("/api/deal/create", json={"preset": "discrepant"}).json()["deal_id"]
    client.post(f"/api/deal/{deal_id}/examine", params={"parser": "template"})
    r = client.post(f"/api/deal/{deal_id}/settle", json={"m": 2})
    assert r.status_code == 200 and r.json()["m"] == 2 and len(r.json()["events"]) == 7
    assert client.get("/api/feed", params={"deal": deal_id}).json() == []
    assert any(d["deal_id"] == deal_id for d in client.get("/api/deals").json())
