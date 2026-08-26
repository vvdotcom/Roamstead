import os

import pytest

from app.agent import agent_enabled, root_agent


@pytest.mark.skipif(
    os.getenv("RUN_STAGING_GEMINI_TESTS") != "1",
    reason="Set RUN_STAGING_GEMINI_TESTS=1 for the intentional billable ADK smoke test.",
)
@pytest.mark.asyncio
async def test_real_adk_gemini_smoke():
    assert agent_enabled()
    from google.adk.runners import InMemoryRunner

    events = await InMemoryRunner(agent=root_agent).run_debug(
        "Reply with one sentence confirming that current listing availability must be independently verified.",
        user_id="staging-test",
        session_id="staging-test",
        quiet=True,
    )
    assert events
    assert any(
        getattr(part, "text", None)
        for event in events
        for part in getattr(getattr(event, "content", None), "parts", []) or []
    )

