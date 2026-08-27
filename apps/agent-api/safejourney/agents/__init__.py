"""The SafeJourney agent fleet, built on Google ADK + Gemini.

Everything here imports ADK/GenAI lazily so the REST API, tools, and monitoring engine keep
working (with deterministic fallbacks) even when those libraries or credentials are absent.
"""
