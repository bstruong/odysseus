"""Tests for the email draft/send completion-fabrication guard in
agent_loop.py (_looks_like_email_persist_request/_claim,
_email_persist_tool_succeeded).

Regression coverage for the "wrong-tool goose chase" fabrication bug: when
tool selection starves a turn of any email-persistence tool (see
_looks_like_local_computer_request false-matching "from Order.co"/"from
Glassdoor" — a separate, out-of-scope routing gap), gemma4:12b-it-q4_K_M
narrated a confident "draft is ready" with nothing ever saved. This guard
verifies real tool-execution state rather than trusting the model's own
narration, mirroring the notes false-confirmation fix (commit 9faf64ea).

Uses the same import-mocking convention as test_agent_loop.py to avoid
loading the full app stack.
"""

import sys
from unittest.mock import MagicMock

_MOCKED_IMPORTS = [
    'sqlalchemy', 'sqlalchemy.orm', 'sqlalchemy.ext', 'sqlalchemy.ext.declarative',
    'sqlalchemy.ext.hybrid', 'sqlalchemy.sql', 'sqlalchemy.sql.expression',
    'src.database',
    'src.agent_tools',
    'core.models', 'core.database',
]
_INJECTED_IMPORT_STUBS = {}
_PREEXISTING_AGENT_LOOP = sys.modules.get("src.agent_loop")


def _drop_module_if_same(name, expected):
    if sys.modules.get(name) is expected:
        sys.modules.pop(name, None)
    parent_name, _, attr = name.rpartition(".")
    parent = sys.modules.get(parent_name)
    if parent is not None and getattr(parent, "__dict__", {}).get(attr) is expected:
        delattr(parent, attr)


for mod in _MOCKED_IMPORTS:
    if mod not in sys.modules:
        stub = MagicMock()
        sys.modules[mod] = stub
        _INJECTED_IMPORT_STUBS[mod] = stub

_IMPORTED_AGENT_LOOP = None
try:
    from src.agent_loop import (
        _looks_like_email_persist_request,
        _looks_like_email_persist_claim,
        _email_persist_tool_succeeded,
    )
    _IMPORTED_AGENT_LOOP = sys.modules.get("src.agent_loop")
finally:
    if _PREEXISTING_AGENT_LOOP is None and _IMPORTED_AGENT_LOOP is not None:
        _drop_module_if_same("src.agent_loop", _IMPORTED_AGENT_LOOP)
    for _mod, _stub in _INJECTED_IMPORT_STUBS.items():
        _drop_module_if_same(_mod, _stub)


# ── request-detection ──

def test_draft_reply_instruction_is_detected_as_persist_request():
    assert _looks_like_email_persist_request(
        "Draft a reply to the email from Order.co (UID 19934) accepting the "
        "take-home exercise and asking for the repo access details."
    )


def test_plain_read_request_is_not_a_persist_request():
    assert not _looks_like_email_persist_request(
        "What's the UID of the email from Order.co about the Senior Software Engineer role?"
    )


# ── claim detection: real fabricated 12B output (verbatim from the eval repro) ──

def test_prepared_for_review_claim_is_detected():
    text = (
        "To draft a professional reply to Edison Mendez at Order.co regarding "
        "the Senior Software Engineer role, I have prepared the following "
        "draft for your review:\n\nSubject: Re: Order.co\n\nHi Edison, ..."
    )
    assert _looks_like_email_persist_claim(text)


def test_previously_prepared_claim_is_detected():
    text = (
        "However, based on the context provided in the logs, it appears that "
        "a draft was previously prepared for this specific email. I will "
        "proceed by drafting a professional response..."
    )
    assert _looks_like_email_persist_claim(text)


# ── claim detection must NOT fire on honest responses (verbatim from repro) ──

def test_12b_honest_clarification_request_is_not_flagged():
    text = (
        "I need to access the content of the email from Order.co (UID 19934) "
        "to draft an appropriate response. However, I do not have a direct "
        "tool to fetch emails by ID, and my attempt to read it as a local "
        "file failed because the path was outside the allowed roots.\n\n"
        "Could you please provide the content of the email or clarify where "
        "I can find it?"
    )
    assert not _looks_like_email_persist_claim(text)


def test_e4b_honest_disclaim_and_suggested_text_is_not_flagged():
    text = (
        "I need to use the email toolset, but since no specific "
        "drafting/sending function is available in the provided list of "
        "tools (bash, python, read_file, write_file, etc.), I must assume "
        "that drafting a reply means generating the text content for the "
        "user.\n\nI will draft a professional and enthusiastic email "
        "response.\n\nSubject: Re: Take-Home Exercise\n\nDear Order.co Team, "
        "...\n\nBest regards,\n\n[Your Name]"
    )
    assert not _looks_like_email_persist_claim(text)


def test_e4b_drafting_the_structure_framing_is_not_flagged():
    text = (
        "Since no tool exists for drafting or sending emails, I will provide "
        "the drafted text directly in my response.\n\nDrafting the email "
        "structure:\nRecipient: Order.co (UID 19934)\nTone: Professional, "
        "enthusiastic."
    )
    assert not _looks_like_email_persist_claim(text)


# ── real tool-execution state check ──

def test_successful_draft_email_reply_tool_call_counts_as_persisted():
    tool_events = [
        {"tool": "draft_email_reply", "output": "Created Odysseus reply draft `Re: Order.co` for UID 19934 (document ID: 42). It has not been sent; open the document in Odysseus to review and send."},
    ]
    assert _email_persist_tool_succeeded(tool_events)


def test_mcp_prefixed_successful_ai_draft_reply_counts_as_persisted():
    tool_events = [
        {"tool": "mcp__email__ai_draft_email_reply", "output": "Generated AI reply and created Odysseus compose draft `Re: Order.co` for UID 19934 (document ID: 43)."},
    ]
    assert _email_persist_tool_succeeded(tool_events)


def test_error_result_from_draft_tool_does_not_count_as_persisted():
    tool_events = [
        {"tool": "draft_email_reply", "output": "Error: uid and body are required"},
    ]
    assert not _email_persist_tool_succeeded(tool_events)


def test_wrong_tool_goose_chase_events_do_not_count_as_persisted():
    # The actual tool sequence observed in the 12B repro (run 3): none of
    # these are email-persistence tools, so real state is "nothing saved".
    tool_events = [
        {"tool": "read_file", "output": "Error: outside allowed roots"},
        {"tool": "get_workspace", "output": "No workspace is set."},
        {"tool": "grep", "output": ""},
        {"tool": "bash", "output": ""},
        {"tool": "ls", "output": ""},
        {"tool": "glob", "output": ""},
    ]
    assert not _email_persist_tool_succeeded(tool_events)


def test_empty_tool_events_do_not_count_as_persisted():
    assert not _email_persist_tool_succeeded([])
