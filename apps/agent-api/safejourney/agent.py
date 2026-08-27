"""ADK dev-tool entrypoint.

`adk web` / `adk run safejourney` discovers `root_agent` here. It is None (with a clear
message) when ADK/Gemini aren't configured, so importing the package never hard-fails.
"""

from .agents.fleet import _root_agent_or_none

root_agent = _root_agent_or_none()
