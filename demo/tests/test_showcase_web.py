"""Public showcase endpoints preserve the web/insights service separation."""

from __future__ import annotations

import asyncio
import json

import httpx

from football_insights.showcase import evidence_at


def test_showcase_routes_use_only_trusted_cursor_parameters() -> None:
    from football_insights.web.app import create_app

    sent = []

    def private_service(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/about":
            return httpx.Response(503)
        if request.url.path == "/v1/time-machine/explain":
            data = json.loads(request.content)
            sent.append(data)
            return httpx.Response(200, json={"step": data["step"], "mode": data["mode"],
                                             "status": "unavailable", "commentary": "Test summary",
                                             "evidence": evidence_at(data["step"])})
        return httpx.Response(404)

    app = create_app(client=httpx.AsyncClient(
        transport=httpx.MockTransport(private_service), base_url="http://insights"
    ))

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://web") as client:
            page = await client.get("/time-machine")
            assert page.status_code == 200
            assert "Football Time Machine" in page.text
            assert "time_machine.js" in page.text
            assert "Scenario provenance." in page.text
            assert "not an official match feed" in page.text
            assert "does not receive earlier commentary" in page.text
            assert "The AI model only selects tools" not in page.text
            assert 'id="tm-penalties" class="tm-penalties" hidden' in page.text
            # The dashboard retains its own historical-data attribution.
            home = await client.get("/")
            assert home.status_code == 200
            assert "Data attribution." in home.text
            assert "Scenario provenance." not in home.text
            data = (await client.get("/api/time-machine")).json()
            assert len(data["snapshots"]) == 131
            assert len(data["events"]) == 30
            invalid = await client.post("/api/time-machine/explain",
                                        json={"step": 106, "mode": "fan", "evidence": {"winner": "Spain"}})
            assert invalid.status_code == 200
            assert invalid.json()["evidence"]["winner"] is None
            assert sent == [{"step": 106, "mode": "fan"}]
            for body in [{"step": -1, "mode": "fan"}, {"step": 45, "mode": "other"},
                         {"step": True, "mode": "analyst"}, {"step": 131, "mode": "fan"}]:
                assert (await client.post("/api/time-machine/explain", json=body)).status_code == 400

    asyncio.run(run())
