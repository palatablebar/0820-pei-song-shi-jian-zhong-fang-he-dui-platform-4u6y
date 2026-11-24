import csv
import io
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from app.business import DomainIssue
from app.delivery.service import deliver
from app.intake.schema import HEADER
from app.review.service import execute, review


def safe(tag, quantity="5"):
    stream = io.StringIO(newline="")
    csv.writer(stream).writerows(
        [
            HEADER,
            [f"W{tag}", f"G{tag}", "watermark", "1", "0", "1", "0", "水位"],
            [f"U{tag}", f"G{tag}", "upsert", "1", "1", "1", quantity, "写入"],
            [f"E{tag}", f"G{tag}", "expected", "0", "0", "0", quantity, "参考"],
        ]
    )
    return stream.getvalue().encode()


def broken(tag):
    stream = io.StringIO(newline="")
    csv.writer(stream).writerows(
        [
            HEADER,
            [f"W{tag}", f"G{tag}", "watermark", "1", "0", "1", "0", "水位"],
            [f"U{tag}", f"G{tag}", "upsert", "1", "1", "1", "5", "写入"],
            [f"E{tag}", f"G{tag}", "expected", "0", "0", "0", "9", "参考"],
            ["BAD", f"G{tag}", "upsert", "1", "1", "2", "5"],
        ]
    )
    return stream.getvalue().encode()


def issued(store, data, note="复核完成，同意签发"):
    run = execute(store, data)
    review(store, run["id"], dict(revision=0, status="APPROVED", note=note))
    return store.load(run["id"])


def held(store, data, note="来源待核对"):
    run = execute(store, data)
    review(store, run["id"], dict(revision=0, status="HELD", note=note))
    return store.load(run["id"])


def test_only_issued_reconciled_runs_are_delivered(store):
    pending = execute(store, safe("01"))
    output = deliver(store, dict(handoff="daily-01"))
    assert output["status"] == "BLOCKED" and output["delivered"] == []
    assert output["blocked"]["run_id"] == pending["id"]
    assert output["blocked"]["reason"] == "NOT_ISSUED"

    issued(store, safe("01"))
    output = deliver(store, dict(handoff="daily-01"))
    assert output["status"] == "DELIVERED"
    assert [entry["run_id"] for entry in output["delivered"]] == [pending["id"]]


def test_held_batch_is_a_gap_not_a_delivery(store):
    bad = held(store, broken("01"))
    output = deliver(store, dict(handoff="daily-01"))
    assert output["status"] == "BLOCKED"
    assert output["blocked"]["run_id"] == bad["id"]
    assert output["blocked"]["reason"] == "NOT_ISSUED"


def test_approved_but_unreconciled_run_is_guarded(store):
    run = issued(store, safe("01"))
    with store.connect() as db:
        db.execute(
            "UPDATE runs SET report=? WHERE id=?",
            (
                json.dumps(
                    {
                        **run["report"],
                        "balance": {**run["report"]["balance"], "releasable": False},
                    },
                    ensure_ascii=False,
                ),
                run["id"],
            ),
        )
    output = deliver(store, dict(handoff="daily-01"))
    assert output["status"] == "BLOCKED"
    assert output["blocked"]["reason"] == "UNRECONCILED"


def test_out_of_order_issue_stops_before_the_gap(store):
    first = issued(store, safe("01"))
    blocked = execute(store, safe("02"))
    later = issued(store, safe("03"))
    output = deliver(store, dict(handoff="daily-01"))
    assert [entry["run_id"] for entry in output["delivered"]] == [first["id"]]
    assert output["blocked"]["run_id"] == blocked["id"]

    review(store, blocked["id"], dict(revision=0, status="APPROVED", note="补齐后签发"))
    nxt = deliver(store, dict(handoff="daily-02", receipt=output["id"]))
    assert [entry["run_id"] for entry in nxt["delivered"]] == [
        blocked["id"],
        later["id"],
    ]
    assert nxt["count"] == 3 and nxt["base"]["receipt"] == output["id"]


def test_catching_up_continues_from_the_original_cursor(store):
    first = issued(store, safe("01"))
    output = deliver(store, dict(handoff="daily-01"))
    second = issued(store, safe("02"))
    nxt = deliver(
        store,
        dict(
            handoff="daily-02",
            receipt=output["id"],
            count=output["count"],
            version=output["version"],
        ),
    )
    assert [entry["run_id"] for entry in nxt["delivered"]] == [second["id"]]
    assert output["delivered"][0]["run_id"] == first["id"]
    assert nxt["size"] == 1 and nxt["base"]["count"] == 1
    assert nxt["count"] == 2 and nxt["base"]["receipt"] == output["id"]


def test_retry_returns_same_receipt(store):
    issued(store, safe("01"))
    first = deliver(store, dict(handoff="daily-01"))
    again = deliver(store, dict(handoff="daily-01"))
    assert first == again
    assert len(store.receipts()) == 1


def test_parallel_retry_appends_single_receipt(store):
    issued(store, safe("01"))
    start = Barrier(4)

    def attempt(_):
        start.wait(3)
        return deliver(store, dict(handoff="daily-01"))

    with ThreadPoolExecutor(max_workers=4) as threads:
        results = list(threads.map(attempt, range(4)))
    assert all(result == results[0] for result in results)
    assert len(store.receipts()) == 1


def test_stale_receipt_is_rejected(store):
    issued(store, safe("01"))
    first = deliver(store, dict(handoff="daily-01"))
    issued(store, safe("02"))
    second = deliver(store, dict(handoff="daily-02", receipt=first["id"]))
    with pytest.raises(DomainIssue, match="RECEIPT_STALE"):
        deliver(store, dict(handoff="daily-03", receipt=first["id"]))
    assert second["base"]["receipt"] == first["id"]


def test_cursor_must_match_receipt(store):
    issued(store, safe("01"))
    first = deliver(store, dict(handoff="daily-01"))
    with pytest.raises(DomainIssue, match="RECEIPT_MISMATCH"):
        deliver(store, dict(handoff="daily-02", receipt=first["id"], count=0))
    with pytest.raises(DomainIssue, match="RECEIPT_MISMATCH"):
        deliver(store, dict(handoff="daily-02", receipt=first["id"], version="nope"))


def test_old_receipt_is_preserved(store):
    issued(store, safe("01"))
    first = deliver(store, dict(handoff="daily-01"))
    issued(store, safe("02"))
    deliver(store, dict(handoff="daily-02", receipt=first["id"]))
    assert store.receipt(first["id"]) == first
    stored = {row["handoff"]: row for row in store.receipts()}
    assert set(stored) == {"daily-01", "daily-02"}


def test_handoff_is_required_and_validated(store):
    with pytest.raises(DomainIssue, match="HANDOFF_REQUIRED"):
        deliver(store, {})
    with pytest.raises(DomainIssue, match="HANDOFF_INVALID"):
        deliver(store, dict(handoff="a b"))
    with pytest.raises(DomainIssue, match="DELIVERY_FIELDS"):
        deliver(store, None)


def test_empty_delivery_is_not_a_receipt(store):
    output = deliver(store, dict(handoff="daily-00"))
    assert output["status"] == "EMPTY" and output["id"] is None
    assert store.receipts() == []


def test_delivery_versions_and_counts_are_verifiable(store):
    issued(store, safe("01"))
    first = deliver(store, dict(handoff="daily-01"))
    assert first["count"] == first["size"] == len(first["delivered"])
    assert first["version"] and first["delivered"][0]["sha256"]
    issued(store, safe("02"))
    second = deliver(
        store,
        dict(
            handoff="daily-02",
            receipt=first["id"],
            count=first["count"],
            version=first["version"],
        ),
    )
    assert second["count"] == 2 and second["version"] != first["version"]
