from app.business import DomainIssue, by_kind, prepared, single


def prepare(rows):
    ceilings = {}
    batch = {}
    later = 0
    for row in by_kind(rows, "watermark"):
        p = row["partition"]
        if p in ceilings:
            raise DomainIssue("WATERMARK_CONFLICT")
        ceilings[p] = row["seq"]
    for row in rows:
        if row["kind"] not in ("upsert", "delete"):
            continue
        p, key, seq = row["partition"], row["entity"], row["seq"]
        if p not in ceilings:
            raise DomainIssue("WATERMARK_MISSING")
        if seq > ceilings[p]:
            later += 1
            continue
        ident = (p, key, seq)
        value = (row["kind"], row["quantity"])
        if ident in batch and batch[ident] != value:
            raise DomainIssue("SOURCE_CONFLICT")
        batch[ident] = value
    return prepared(
        len(batch),
        {"deferred_events": later, "partitions": len(ceilings)},
        (batch, single(rows, "expected")["quantity"]),
    )
