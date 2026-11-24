import io

from app.intake.schema import HEADER
from conftest import csv_data


def safe(tag):
    return csv_data(
        [
            [f"W{tag}", f"G{tag}", "watermark", "1", "0", "1", "0", "水位"],
            [f"U{tag}", f"G{tag}", "upsert", "1", "1", "1", "5", "写入"],
            [f"E{tag}", f"G{tag}", "expected", "0", "0", "0", "5", "参考"],
        ]
    )


def issue(client, data, note="复核完成，同意签发"):
    run = client.post("/api/runs", data={"file": (io.BytesIO(data), "in.csv")}).json
    response = client.patch(
        f"/api/runs/{run['id']}",
        json=dict(revision=0, status="APPROVED", note=note),
    )
    assert response.status_code == 200
    return run


def test_delivery_flows_through_http(client):
    run = issue(client, safe("01"))
    created = client.post("/api/deliveries", json=dict(handoff="daily-01"))
    assert created.status_code == 200
    body = created.json
    assert body["status"] == "DELIVERED"
    assert [entry["run_id"] for entry in body["delivered"]] == [run["id"]]

    again = client.post("/api/deliveries", json=dict(handoff="daily-01"))
    assert again.json == body

    fetched = client.get("/api/deliveries/" + body["id"])
    assert fetched.status_code == 200 and fetched.json == body
    listed = client.get("/api/deliveries").json["items"]
    assert [row["handoff"] for row in listed] == ["daily-01"]


def test_delivery_reports_gap_without_receipt(client):
    pending = client.post(
        "/api/runs", data={"file": (io.BytesIO(safe("01")), "in.csv")}
    ).json
    body = client.post("/api/deliveries", json=dict(handoff="daily-01")).json
    assert body["status"] == "BLOCKED" and body["id"] is None
    assert body["blocked"]["run_id"] == pending["id"]
    assert client.get("/api/deliveries").json["items"] == []


def test_delivery_rejects_bad_handoff(client):
    assert client.post("/api/deliveries", json={}).status_code == 422
    assert (
        client.post("/api/deliveries", json=dict(handoff="a b")).json["code"]
        == "HANDOFF_INVALID"
    )
    assert client.post("/api/deliveries").status_code == 422


def test_unknown_receipt_is_404(client):
    assert client.get("/api/deliveries/unknown").status_code == 404
    assert (
        client.post("/api/deliveries", json=dict(handoff="x", receipt="unknown"))
        .status_code
        == 404
    )


def test_stale_cursor_is_conflict(client):
    issue(client, safe("01"))
    first = client.post("/api/deliveries", json=dict(handoff="daily-01")).json
    issue(client, safe("02"))
    client.post("/api/deliveries", json=dict(handoff="daily-02", receipt=first["id"]))
    stale = client.post(
        "/api/deliveries", json=dict(handoff="daily-03", receipt=first["id"])
    )
    assert stale.status_code == 409 and stale.json["code"] == "RECEIPT_STALE"
    mismatched = client.post(
        "/api/deliveries", json=dict(handoff="daily-04", count=99, version="bad")
    )
    assert mismatched.status_code == 409
    assert mismatched.json["code"] == "RECEIPT_MISMATCH"
