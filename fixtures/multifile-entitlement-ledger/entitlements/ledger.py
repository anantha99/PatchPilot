class SeatLedger:
    def __init__(self) -> None:
        self.entries: list[dict] = []
        self.current_seats: dict[str, int] = {}

    def record(self, account_id: str, seats: int) -> dict:
        self.current_seats[account_id] = seats
        entry = {"account_id": account_id, "delta": seats, "seats": seats}
        self.entries.append(entry)
        return entry
