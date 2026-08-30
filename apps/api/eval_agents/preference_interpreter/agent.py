from app.agent import build_clarification_agent


# ADK CLI evaluation and optimization target only this measurable,
# approval-safe collaboration surface. Optimized output is a candidate and is
# never activated by this module.
root_agent = build_clarification_agent()
