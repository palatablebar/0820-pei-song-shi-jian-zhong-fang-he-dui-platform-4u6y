"""下游续取：按批次登记顺序交付已签发且对账一致的重放结果。

交付位置只由两个事实决定：批次是否已签发（``APPROVED`` 且对账可签发），
以及下游已经持有哪些回执。登记顺序中一旦出现尚未签发或对账不一致的批次，
交付就停在该缺口之前；缺口补齐后，从原回执的游标继续。回执只追加，旧回执
保持原样，同一交接重试返回同一份回执。
"""

import json
import re
from datetime import datetime, timezone
from hashlib import sha256

from app.business import DomainIssue

SCHEMA = "delivery-receipt/1"
HANDOFF = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")


def now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def item(run):
    report = run["report"]
    manifest = report["manifest"]
    return {
        "run_id": run["id"],
        "seq": run["seq"],
        "revision": run["revision"],
        "reviewed": run["reviewed"],
        "rule_version": manifest["version"],
        "sha256": manifest["sha256"],
        "cases": report["cases"],
        "balance": report["balance"],
    }


def signature(entry):
    return sha256(
        canonical(
            {
                "run_id": entry["run_id"],
                "seq": entry["seq"],
                "revision": entry["revision"],
                "sha256": entry["sha256"],
            }
        ).encode()
    ).hexdigest()


def version_of(entries, base):
    """累计摘要：续取的新回执必须延续上一份回执的数量和版本。"""
    items = sha256("|".join(signature(entry) for entry in entries).encode()).hexdigest()
    return sha256(f"{SCHEMA}|{base}|{items}".encode()).hexdigest()


def receipt_id(handoff):
    return sha256(f"{SCHEMA}:{handoff}".encode()).hexdigest()


def verify(receipt):
    base_count = receipt["base"]["count"] if receipt.get("base") else 0
    base_version = receipt["base"]["version"] if receipt.get("base") else ""
    if receipt["count"] != base_count + len(receipt["delivered"]):
        raise DomainIssue("RECEIPT_CORRUPT")
    if receipt["version"] != version_of(receipt["delivered"], base_version):
        raise DomainIssue("RECEIPT_CORRUPT")
    return receipt


def deliverable(run):
    return run["status"] == "APPROVED" and bool(
        run["report"].get("balance", {}).get("releasable")
    )


def gap(run):
    reason = "NOT_ISSUED" if run["status"] != "APPROVED" else "UNRECONCILED"
    return {
        "run_id": run["id"],
        "seq": run["seq"],
        "status": run["status"],
        "reason": reason,
    }


def _handoff(values):
    if not isinstance(values, dict):
        raise DomainIssue("DELIVERY_FIELDS")
    raw = values.get("handoff")
    if not isinstance(raw, str) or not raw.strip():
        raise DomainIssue("HANDOFF_REQUIRED")
    handoff = raw.strip()
    if not HANDOFF.fullmatch(handoff):
        raise DomainIssue("HANDOFF_INVALID")
    return handoff


def _head(db):
    return db.execute(
        "SELECT payload FROM receipts ORDER BY position DESC LIMIT 1"
    ).fetchone()


def _parent(values, db, head):
    """续取必须从最新回执出发；显式给出的回执同时校验归属与数量版本。"""
    requested = values.get("receipt")
    if isinstance(requested, dict):
        requested = requested.get("id")
        if not isinstance(requested, str) or not requested:
            raise DomainIssue("RECEIPT_NOT_FOUND")
    if requested is None:
        return head
    if not isinstance(requested, str):
        raise DomainIssue("RECEIPT_NOT_FOUND")
    found = db.execute(
        "SELECT payload FROM receipts WHERE id=?", (requested,)
    ).fetchone()
    if found is None:
        raise DomainIssue("RECEIPT_NOT_FOUND")
    if head is None or head["id"] != requested:
        raise DomainIssue("RECEIPT_STALE")
    return verify(json.loads(found["payload"]))


def _check_cursor(values, parent):
    """续取时客户端回传上一份回执的数量和版本，必须与链头一致。"""
    count = values.get("count")
    version = values.get("version")
    receipt = values.get("receipt")
    if isinstance(receipt, dict):
        count = receipt.get("count", count)
        version = receipt.get("version", version)
    if count is None and version is None:
        return
    expected_count = parent["count"] if parent else 0
    expected_version = parent["version"] if parent else ""
    if count is not None and (type(count) is not int or count != expected_count):
        raise DomainIssue("RECEIPT_MISMATCH")
    if version is not None and version != expected_version:
        raise DomainIssue("RECEIPT_MISMATCH")


def _shell(handoff, parent, blocked):
    return {
        "schema": SCHEMA,
        "id": None,
        "handoff": handoff,
        "origin": parent["id"] if parent else None,
        "created": now(),
        "status": "BLOCKED" if blocked else "EMPTY",
        "position": parent["position"] if parent else 0,
        "count": parent["count"] if parent else 0,
        "size": 0,
        "base": (
            {
                "receipt": parent["id"],
                "count": parent["count"],
                "version": parent["version"],
            }
            if parent
            else None
        ),
        "version": parent["version"] if parent else "",
        "blocked": blocked,
        "delivered": [],
    }


def deliver(store, values):
    """基于签发与接收事实推进交付，返回回执（含本次交付结果）。

    同一 ``handoff`` 重试返回已经落库的那一份，不新增回执。
    """
    handoff = _handoff(values)
    with store.transaction() as db:
        existing = db.execute(
            "SELECT payload FROM receipts WHERE handoff=?", (handoff,)
        ).fetchone()
        if existing is not None:
            return verify(json.loads(existing["payload"]))
        head_row = _head(db)
        head = verify(json.loads(head_row["payload"])) if head_row else None
        parent = _parent(values, db, head)
        _check_cursor(values, parent)
        position = parent["position"] if parent else 0
        base_count = parent["count"] if parent else 0
        base_version = parent["version"] if parent else ""

        entries, blocked = [], None
        for row in db.execute(
            "SELECT * FROM runs WHERE seq>? ORDER BY seq", (position,)
        ):
            run = dict(row)
            run["report"] = json.loads(run["report"])
            if not deliverable(run):
                blocked = gap(run)
                break
            entries.append(item(run))

        if not entries:
            return _shell(handoff, parent, blocked)

        position = entries[-1]["seq"]
        taken = db.execute(
            "SELECT handoff FROM receipts WHERE position=?", (position,)
        ).fetchone()
        if taken is not None:
            raise DomainIssue("RECEIPT_CONFLICT")

        receipt = {
            "schema": SCHEMA,
            "id": receipt_id(handoff),
            "handoff": handoff,
            "origin": parent["id"] if parent else None,
            "created": now(),
            "status": "DELIVERED",
            "position": position,
            "count": base_count + len(entries),
            "size": len(entries),
            "base": (
                {
                    "receipt": parent["id"],
                    "count": base_count,
                    "version": base_version,
                }
                if parent
                else None
            ),
            "version": version_of(entries, base_version),
            "blocked": blocked,
            "delivered": entries,
        }
        db.execute(
            "INSERT INTO receipts(id,handoff,origin,position,count,created,payload) "
            "VALUES (?,?,?,?,?,?,?) ON CONFLICT DO NOTHING",
            (
                receipt["id"],
                receipt["handoff"],
                receipt["origin"],
                receipt["position"],
                receipt["count"],
                receipt["created"],
                canonical(receipt),
            ),
        )
        stored = db.execute(
            "SELECT payload FROM receipts WHERE handoff=?", (handoff,)
        ).fetchone()
        return verify(json.loads(stored["payload"]))


def receipt(store, receipt_id):
    return verify(store.receipt(receipt_id))
