"""User-requested overlap fixes: the speed arithmetic, and both fixes end to end."""

import pytest

from editor_service import overlaps
from editor_service.tests.test_api_e2e import drain, env  # noqa: F401  (fixture)
from editor_service.tests.test_db import URL


def line(raw, speed=1.0, trims=0.0, available=2.0, text="x" * 40):
    return {"raw_s": raw, "speed": speed, "trims_s": trims, "length_s": raw - trims, "available_s": available, "text": text}


def test_speed_to_fit_is_exact_and_capped():
    assert overlaps.speed_to_fit(line(3.0, available=2.0)) == 1.5             # 3.0 s into 2.0 s
    assert overlaps.speed_to_fit(line(3.0, speed=1.2, available=2.0)) == 1.8  # raw is the 1.2 take
    assert overlaps.speed_to_fit(line(3.0, trims=0.5, available=2.0)) == 1.2  # trims stay: 3.0 into 2.5
    assert overlaps.speed_to_fit(line(5.0, available=2.0)) is None            # would need 2.5x
    assert overlaps.speed_to_fit(line(2.01, available=2.0)) == 1.01           # rounds up, never under


def test_shorten_budget_scales_with_the_time_available():
    assert overlaps.shorten_budget(line(4.0, available=2.0, text="y" * 100)) == 46   # half the time, 92% margin


@pytest.mark.skipif(not URL, reason="DATABASE_URL_TEST not set")
@pytest.mark.parametrize("mode", ["speed", "shorten"])
def test_fix_removes_the_overlap(env, mode):  # noqa: F811
    from fastapi.testclient import TestClient
    from editor_service.main import app

    with TestClient(app) as c:
        pid = c.post("/api/editor/projects", json={
            "asset_id": "11111111-1111-1111-1111-111111111111", "name": "Ov", "input_kind": "script",
            "script_text": "Welcome to the demo. Haha, this part is funny! And this is the end.",
            "src_lang": "en-IN", "tgt_lang": "en-IN", "voice": {"mode": "persona", "voice_id": "Lakshmi"}}).json()["id"]
        drain()
        chunks = c.get(f"/api/editor/projects/{pid}").json()["chunks"]
        found = c.get(f"/api/editor/projects/{pid}/overlaps").json()
        if not found:                        # make one: pull chunk 2 back to start halfway through chunk 1
            a, b = chunks[0], chunks[1]
            shift = (float(a["anchor_src_s"]) + float(a["audio_duration_s"]) / 2) - float(b["anchor_src_s"])
            tl = c.get(f"/api/editor/projects/{pid}/timeline").json()
            r = c.post(f"/api/editor/projects/{pid}/timeline/ops", json={"base_version": tl["version"], "ops": [
                {"type": "voice.set", "chunk_id": b["id"], "fields": {"offset": round(shift, 3)}}]})
            assert r.status_code == 200, r.text
            found = c.get(f"/api/editor/projects/{pid}/overlaps").json()
        assert found and all(x["length_s"] > x["available_s"] for x in found)
        before = {x["id"]: x for x in chunks}
        ids = [x["chunk_id"] for x in found]

        r = c.post(f"/api/editor/projects/{pid}/overlaps/fix", json={"mode": mode})
        assert r.status_code == 200, r.text
        assert sorted(f["chunk_id"] for f in r.json()["fixed"]) == sorted(ids) and r.json()["skipped"] == []
        drain()
        after = {x["id"]: x for x in c.get(f"/api/editor/projects/{pid}").json()["chunks"]}
        for f in r.json()["fixed"]:
            ch = after[f["chunk_id"]]
            assert ch["status"] == "ready"
            if mode == "speed":
                assert float(ch["speed"]) == pytest.approx(f["speed"]) and f["speed"] > 1.0
            else:
                assert len(ch["text"]) < len(before[f["chunk_id"]]["text"])
        assert c.get(f"/api/editor/projects/{pid}/overlaps").json() == []
