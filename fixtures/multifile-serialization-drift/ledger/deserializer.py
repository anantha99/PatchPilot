def load_invoice(payload: dict[str, int | str]) -> dict[str, int | str]:
    return {"id": payload["id"], "amount_cents": payload["total"]}
