def dump_invoice(invoice: dict[str, int | str]) -> dict[str, int | str]:
    return {"id": invoice["id"], "total": invoice["amount_cents"]}
