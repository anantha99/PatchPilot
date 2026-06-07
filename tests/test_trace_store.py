import asyncio

from patchpilot.observability.tracing import TraceStore


def test_trace_store_redacts_sensitive_payload_values(tmp_path) -> None:
    store = TraceStore(tmp_path)

    asyncio.run(
        store.record(
            trace_id="tr_secret",
            session_id="sess",
            event_type="model.started",
            name="openrouter",
            payload={"openrouter_api_key": "sk-test", "nested": {"Authorization": "Bearer sk-test"}},
        )
    )

    events = store.read("tr_secret")

    assert events[0].payload["openrouter_api_key"] == "[redacted]"
    assert events[0].payload["nested"]["Authorization"] == "[redacted]"
