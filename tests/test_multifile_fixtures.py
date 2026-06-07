from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).parents[1]
FIXTURES = ROOT / "fixtures"
COPY_IGNORE = shutil.ignore_patterns(".patchpilot", ".pytest_cache", "__pycache__")


FULL_FIXES: dict[str, list[tuple[str, str, str]]] = {
    "multifile-calendar-window": [
        ("calendar_rules/constants.py", "WEEKEND_DAYS = {5}", "WEEKEND_DAYS = {5, 6}"),
        ("calendar_rules/window.py", "return 0 <= days_from_now < MAX_BOOKING_DAYS", "return 0 <= days_from_now <= MAX_BOOKING_DAYS"),
    ],
    "multifile-inventory-state": [
        ("inventory/policy.py", "MINIMUM_REMAINING_STOCK = 10", "MINIMUM_REMAINING_STOCK = 12"),
        ("inventory/state.py", "return on_hand - quantity > MINIMUM_REMAINING_STOCK", "return on_hand - quantity >= MINIMUM_REMAINING_STOCK"),
    ],
    "multifile-entitlement-ledger": [
        (
            "entitlements/events.py",
            "        \"status\": payload[\"status\"],\n        \"plan\": payload[\"plan\"],\n        \"seats\": payload[\"seats\"],",
            "        \"status\": str(payload[\"status\"]).strip().lower().replace(\"-\", \"_\"),\n        \"plan\": str(payload[\"plan\"]).strip().lower(),\n        \"seats\": int(payload[\"seats\"]),",
        ),
        (
            "entitlements/policy.py",
            "ACTIVE_STATUSES = {\"active\"}\nPAID_PLANS = {\"pro\", \"enterprise\"}\n\n\ndef can_access_feature(account: dict) -> bool:\n    return (\n        account.get(\"plan\") in PAID_PLANS\n        and account.get(\"status\") == \"active\"\n        and account.get(\"seats\", 0) > 0\n    )\n",
            "ACTIVE_STATUSES = {\"active\", \"trialing\"}\nPAID_PLANS = {\"pro\", \"enterprise\"}\n\n\ndef can_access_feature(account: dict) -> bool:\n    return (\n        account.get(\"plan\") in PAID_PLANS\n        and account.get(\"status\") in ACTIVE_STATUSES\n        and account.get(\"seats\", 0) > 0\n    )\n",
        ),
        (
            "entitlements/ledger.py",
            "    def record(self, account_id: str, seats: int) -> dict:\n        self.current_seats[account_id] = seats\n        entry = {\"account_id\": account_id, \"delta\": seats, \"seats\": seats}\n        self.entries.append(entry)\n        return entry",
            "    def record(self, account_id: str, seats: int) -> dict:\n        previous = self.current_seats.get(account_id, 0)\n        self.current_seats[account_id] = seats\n        entry = {\"account_id\": account_id, \"delta\": seats - previous, \"seats\": seats}\n        self.entries.append(entry)\n        return entry",
        ),
        (
            "entitlements/processor.py",
            "    event = normalize_event(payload)\n    account = accounts.setdefault(event[\"account_id\"], {})\n    account[\"status\"] = event[\"status\"]\n    account[\"plan\"] = event[\"plan\"]\n    account[\"seats\"] = event[\"seats\"]\n    ledger_entry = ledger.record(event[\"account_id\"], event[\"seats\"])\n\n    if event[\"event_id\"] in processed_events:\n        return {\n            \"applied\": False,\n            \"account\": account,\n            \"ledger_entry\": ledger_entry,\n            \"can_access\": can_access_feature(account),\n        }\n\n    processed_events.add(event[\"event_id\"])",
            "    event = normalize_event(payload)\n    account = accounts.setdefault(event[\"account_id\"], {})\n    if event[\"event_id\"] in processed_events:\n        return {\n            \"applied\": False,\n            \"account\": account,\n            \"ledger_entry\": None,\n            \"can_access\": can_access_feature(account),\n        }\n\n    processed_events.add(event[\"event_id\"])\n    if event[\"account_id\"] not in ledger.current_seats:\n        ledger.current_seats[event[\"account_id\"]] = int(account.get(\"seats\", 0) or 0)\n    account[\"status\"] = event[\"status\"]\n    account[\"plan\"] = event[\"plan\"]\n    account[\"seats\"] = event[\"seats\"]\n    ledger_entry = ledger.record(event[\"account_id\"], event[\"seats\"])",
        ),
    ],
    "multifile-parser-validator": [
        ("querytools/parser.py", "        key, value = item.split(\"=\", 1)\n        pairs[key] = value", "        key, value = item.split(\"=\", 1)\n        pairs[key.strip()] = value.strip()"),
        (
            "querytools/validator.py",
            "def validate_pairs(pairs: dict[str, str]) -> None:\n    for key, value in pairs.items():\n        if not key:\n            raise ValueError(\"blank key\")\n        if value == \"\":\n            raise ValueError(\"blank value\")\n",
            "def validate_pairs(pairs: dict[str, str]) -> None:\n    for key, value in pairs.items():\n        if not key.strip():\n            raise ValueError(\"blank key\")\n        if value.strip() == \"\":\n            raise ValueError(\"blank value\")\n",
        ),
    ],
    "multifile-permissions-contract": [
        ("access/defaults.py", "\"role\": \"user\"", "\"role\": \"member\""),
        ("access/permissions.py", "{\"admin\", \"user\"}", "{\"admin\", \"member\"}"),
    ],
    "multifile-profile-contract": [
        ("profiles/normalizer.py", "return email.lower()", "return email.strip().lower()"),
        (
            "profiles/validators.py",
            "return \"@\" in email and email == email.lower()",
            "local, _, domain = email.partition(\"@\")\n    return bool(local and domain) and email == email.strip().lower()",
        ),
    ],
    "multifile-reexport-drift": [
        ("texttools/slugs.py", "replace(\" \", \"_\")", "replace(\" \", \"-\")"),
        ("texttools/__init__.py", "from .slugs import old_slugify as slugify", "from .slugs import slugify"),
    ],
    "multifile-retry-partial-trap": [
        ("shop/discounts.py", "return percent", "return 1 - percent / 100"),
        ("shop/cart.py", "return round(subtotal - discount_multiplier(discount_percent), 2)", "return round(subtotal * discount_multiplier(discount_percent), 2)"),
    ],
    "multifile-serialization-drift": [
        ("ledger/serializer.py", "\"total\": invoice[\"amount_cents\"]", "\"amount\": invoice[\"amount_cents\"]"),
        ("ledger/deserializer.py", "payload[\"total\"]", "payload[\"amount\"]"),
    ],
    "multifile-shipping-rules": [
        ("shipping/constants.py", "FREE_SHIPPING_THRESHOLD = 50.0", "FREE_SHIPPING_THRESHOLD = 75.0"),
        ("shipping/rates.py", "if subtotal > FREE_SHIPPING_THRESHOLD:", "if subtotal >= FREE_SHIPPING_THRESHOLD:"),
    ],
    "multifile-taxes-rounding": [
        ("billing/tax.py", "TAX_RATE = 0.08", "TAX_RATE = 0.083"),
        (
            "billing/invoice.py",
            "    subtotal = sum(round(item, 2) for item in items)\n    tax = sum(tax_for(item) for item in items)",
            "    subtotal = round(sum(items), 2)\n    tax = tax_for(subtotal)",
        ),
    ],
}


DIRECT_TEST_MARKERS: dict[tuple[str, str], list[str]] = {
    ("multifile-calendar-window", "calendar_rules/constants.py"): ["MAX_BOOKING_DAYS", "WEEKEND_DAYS"],
    ("multifile-calendar-window", "calendar_rules/window.py"): ["can_book("],
    ("multifile-entitlement-ledger", "entitlements/events.py"): ["normalize_event("],
    ("multifile-entitlement-ledger", "entitlements/policy.py"): ["can_access_feature("],
    ("multifile-entitlement-ledger", "entitlements/ledger.py"): ["SeatLedger(", "ledger.record("],
    ("multifile-entitlement-ledger", "entitlements/processor.py"): ["process_subscription_event("],
    ("multifile-inventory-state", "inventory/policy.py"): ["MINIMUM_REMAINING_STOCK"],
    ("multifile-inventory-state", "inventory/state.py"): ["can_reserve("],
    ("multifile-parser-validator", "querytools/parser.py"): ["parse_pairs("],
    ("multifile-parser-validator", "querytools/validator.py"): ["validate_pairs("],
    ("multifile-permissions-contract", "access/defaults.py"): ["default_account("],
    ("multifile-permissions-contract", "access/permissions.py"): ["can_read("],
    ("multifile-profile-contract", "profiles/normalizer.py"): ["normalize_email("],
    ("multifile-profile-contract", "profiles/validators.py"): ["is_valid_email("],
    ("multifile-reexport-drift", "texttools/__init__.py"): ["texttools.slugify is texttools.slugs.slugify"],
    ("multifile-reexport-drift", "texttools/slugs.py"): ["direct_slugify("],
    ("multifile-retry-partial-trap", "shop/discounts.py"): ["discount_multiplier("],
    ("multifile-retry-partial-trap", "shop/cart.py"): ["cart_total("],
    ("multifile-serialization-drift", "ledger/serializer.py"): ["dump_invoice("],
    ("multifile-serialization-drift", "ledger/deserializer.py"): ["load_invoice("],
    ("multifile-shipping-rules", "shipping/constants.py"): ["FREE_SHIPPING_THRESHOLD"],
    ("multifile-shipping-rules", "shipping/rates.py"): ["shipping_cost("],
    ("multifile-taxes-rounding", "billing/tax.py"): ["tax_for("],
    ("multifile-taxes-rounding", "billing/invoice.py"): ["invoice_total("],
}


def test_multifile_fixture_expected_files_have_direct_behavioral_tests() -> None:
    for fixture in sorted(FULL_FIXES):
        metadata = json.loads((FIXTURES / fixture / "fixture.json").read_text(encoding="utf-8"))
        test_text = "\n".join(path.read_text(encoding="utf-8") for path in (FIXTURES / fixture / "tests").glob("test_*.py"))
        for source_file in metadata["expected_changed_source_files"]:
            assert "tests/" not in source_file
            markers = DIRECT_TEST_MARKERS[(fixture, source_file)]
            assert any(marker in test_text for marker in markers), f"{fixture} lacks direct test marker for {source_file}"


def test_multifile_fixtures_fail_before_repair(tmp_path: Path) -> None:
    for fixture in sorted(FULL_FIXES):
        repo = _copy_fixture(fixture, tmp_path / f"{fixture}-broken")

        result = _run_pytest(repo)

        assert result.returncode != 0, f"{fixture} unexpectedly passed before repair\n{result.stdout}\n{result.stderr}"


def test_known_one_file_partial_repairs_still_fail(tmp_path: Path) -> None:
    for fixture, fixes in sorted(FULL_FIXES.items()):
        repo = _copy_fixture(fixture, tmp_path / f"{fixture}-partial")
        _apply_fixes(repo, fixes[:1])

        result = _run_pytest(repo)

        assert result.returncode != 0, f"{fixture} partial repair unexpectedly passed\n{result.stdout}\n{result.stderr}"


def test_known_full_multifile_repairs_pass(tmp_path: Path) -> None:
    for fixture, fixes in sorted(FULL_FIXES.items()):
        repo = _copy_fixture(fixture, tmp_path / f"{fixture}-full")
        _apply_fixes(repo, fixes)

        result = _run_pytest(repo)

        assert result.returncode == 0, f"{fixture} full repair failed\n{result.stdout}\n{result.stderr}"


def _copy_fixture(fixture: str, dest: Path) -> Path:
    shutil.copytree(FIXTURES / fixture, dest, ignore=COPY_IGNORE)
    return dest


def _apply_fixes(repo: Path, fixes: list[tuple[str, str, str]]) -> None:
    for rel, before, after in fixes:
        path = repo / rel
        text = path.read_text(encoding="utf-8")
        assert before in text, f"{rel} missing expected text"
        path.write_text(text.replace(before, after), encoding="utf-8")


def _run_pytest(repo: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        cwd=repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
    )
