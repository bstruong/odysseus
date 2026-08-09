"""Every builtin email tool must be in _DOMAIN_TOOL_MAP["email"], or it's
unreachable for a neutrally-worded query — confirmed the hard way, a 5th
time.

Found during a cross-model benchmark (Phase 2 session 5): search_emails,
draft_email, draft_email_reply, ai_draft_email_reply, and
download_attachment were correctly present in TOOL_SECTIONS,
ToolIndex._KEYWORD_HINTS, FUNCTION_TOOL_SCHEMAS, and
ToolIndex.BUILTIN_TOOL_DESCRIPTIONS (all fixed in sessions 1-4), but were
STILL missing from a fifth, separate hand-maintained list:
agent_loop._DOMAIN_TOOL_MAP["email"].

This list is the fallback consulted when a message is classified into the
"email" domain by the NLP domain classifier WITHOUT also matching a
literal keyword substring in ToolIndex._KEYWORD_HINTS (e.g. "Do I have
anything from A3 Tech Group about a partnership for my saber project?" —
no "email"/"mail"/"reply"/etc. substring present). Confirmed live: this
silently withheld search_emails from all 4 models tested in a cross-model
benchmark, identically, regardless of which model was running — an
infra-level confound, not a model-quality signal.

Kept in sync via direct derivation from tool_security.BUILTIN_EMAIL_TOOLS
(see agent_loop.py) rather than a second hand-typed literal, so this can't
drift the same way again structurally. This test is the guard for the
mapping's *keys* — it fails loudly if a future edit reverts to a hand-typed
literal that omits any canonical email tool.
"""
import pytest

from src.tool_security import BUILTIN_EMAIL_TOOLS
from src.agent_loop import _DOMAIN_TOOL_MAP


def test_all_builtin_email_tools_are_in_domain_tool_map_email():
    missing = sorted(BUILTIN_EMAIL_TOOLS - _DOMAIN_TOOL_MAP["email"])
    assert missing == [], (
        f"Builtin email tools missing from _DOMAIN_TOOL_MAP['email'] "
        f"(unreachable for a neutrally-worded 'email'-domain query that "
        f"doesn't also hit a _KEYWORD_HINTS literal): {missing}"
    )


@pytest.mark.parametrize("tool_name", sorted(BUILTIN_EMAIL_TOOLS))
def test_each_builtin_email_tool_is_in_domain_tool_map_email(tool_name):
    assert tool_name in _DOMAIN_TOOL_MAP["email"], (
        f"{tool_name} missing from _DOMAIN_TOOL_MAP['email']"
    )


def test_previously_missing_tools_are_now_present():
    """Names the specific regression this session found (Phase 2 session 6),
    so a future revert fails loudly and specifically rather than just
    showing up in the sweeps above."""
    previously_missing = {
        "search_emails", "draft_email", "draft_email_reply",
        "ai_draft_email_reply", "download_attachment",
    }
    still_missing = previously_missing - _DOMAIN_TOOL_MAP["email"]
    assert still_missing == set(), f"Regressed in _DOMAIN_TOOL_MAP['email']: {sorted(still_missing)}"
