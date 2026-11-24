from app.business import measured


def compute(data):
    batch, target = data
    winners = {}
    for (part, entity, seq), (kind, qty) in sorted(batch.items()):
        winners[(part, entity)] = (seq, kind, qty)
    live = {f"{p}/{e}": q for (p, e), (_, k, q) in winners.items() if k == "upsert"}
    dead = {f"{p}/{e}": seq for (p, e), (seq, k, _) in winners.items() if k == "delete"}
    return measured(
        sum(live.values()), target, "件", {"live": live, "tombstones": dead}
    )
