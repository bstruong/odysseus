"""Every builtin email tool must (a) have a TOOL_SECTIONS entry and (b) be in
the email _KEYWORD_HINTS set, or it's unreachable — confirmed the hard way.

Found during a real-inbox eval: search_emails, draft_email, draft_email_reply,
ai_draft_email_reply, and download_attachment were fully implemented and
correctly security-classified (tool_security.BUILTIN_EMAIL_TOOLS), but were
missing from BOTH of the places that actually make a builtin email tool
reachable for a given query:

1. agent_loop.TOOL_SECTIONS — documents the tool for the system prompt.
2. tool_index.ToolIndex._KEYWORD_HINTS — the email-keyword entry that force-
   includes email tools in `relevant_tools` for a query. This turned out to
   be the *load-bearing* one: mcp_manager.get_tool_descriptions_for_prompt()
   explicitly skips every builtin MCP server ("they're already in the agent
   prompt") when building the semantic-retrieval embedding corpus, so
   ToolIndex.retrieve() can NEVER surface a builtin email tool by embedding
   similarity — _KEYWORD_HINTS is the only mechanism that does. Fixing (1)
   alone was necessary but not sufficient; a tool missing from (2) stayed
   unreachable even after (1) was fixed, confirmed by rerunning the exact
   live eval prompt that first surfaced this bug. See NOTES.md for the full
   writeup and the two-stage discovery.

A tool missing from either place can never be called, by any model,
regardless of query phrasing — confirmed live: `docker compose logs | grep
-c search_emails` returned 0 across this deployment's full retained log
history before the fix.

This test is the guard against the bug recurring silently for any future
builtin email tool.
"""
import pytest

from src.tool_security import BUILTIN_EMAIL_TOOLS
from src.agent_loop import TOOL_SECTIONS
from src.tool_index import ToolIndex


def _email_keyword_hint_tools() -> set:
    for keywords, tools in ToolIndex._KEYWORD_HINTS.items():
        if "email" in keywords:
            return set(tools)
    raise AssertionError("No email-flavored entry found in ToolIndex._KEYWORD_HINTS")


def test_all_builtin_email_tools_have_tool_sections_entries():
    missing = sorted(BUILTIN_EMAIL_TOOLS - set(TOOL_SECTIONS.keys()))
    assert missing == [], (
        f"Builtin email tools with no TOOL_SECTIONS entry (undocumented in "
        f"the system prompt): {missing}"
    )


def test_all_builtin_email_tools_are_in_the_email_keyword_hint_set():
    missing = sorted(BUILTIN_EMAIL_TOOLS - _email_keyword_hint_tools())
    assert missing == [], (
        f"Builtin email tools missing from ToolIndex._KEYWORD_HINTS's email "
        f"entry (unreachable via relevant_tools for any 'email'-flavored "
        f"query, since RAG retrieval never indexes builtin MCP tools): {missing}"
    )


@pytest.mark.parametrize("tool_name", sorted(BUILTIN_EMAIL_TOOLS))
def test_each_builtin_email_tool_has_a_nonempty_tool_sections_entry(tool_name):
    assert tool_name in TOOL_SECTIONS, f"{tool_name} missing from TOOL_SECTIONS"
    assert TOOL_SECTIONS[tool_name].strip(), f"{tool_name}'s TOOL_SECTIONS entry is empty"


def test_previously_missing_tools_are_now_present_in_both_places():
    """Names the specific regression this session found, so a future revert
    fails loudly and specifically rather than just showing up in the sweeps
    above."""
    previously_missing = {
        "search_emails", "draft_email", "draft_email_reply",
        "ai_draft_email_reply", "download_attachment",
    }
    still_missing_sections = previously_missing - set(TOOL_SECTIONS.keys())
    assert still_missing_sections == set(), f"Regressed in TOOL_SECTIONS: {sorted(still_missing_sections)}"
    still_missing_hints = previously_missing - _email_keyword_hint_tools()
    assert still_missing_hints == set(), f"Regressed in _KEYWORD_HINTS: {sorted(still_missing_hints)}"
