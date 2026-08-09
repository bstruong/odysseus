"""Regression: list_emails' default max_results (20) applied even to
unread_only/unresponded_only ("what needs attention") queries, with no
pagination the caller could reach for instead. A caller — model or human —
that never thinks to pass max_results only ever sees the newest 20 of
however many actually need attention, silently, a different subset each
time as new mail arrives ahead of the cutoff.

This was (part of) the Task A triage coverage gap: qwen3:8b surfaced only
~5-10 of 52 real unread threads per run, a different subset each run.
Confirmed live against the real account behind this deployment: 58 real
unread messages, `list_emails(unread_only=True)` with no max_results
returned exactly 20 before this fix.

Fix: when the caller doesn't pass max_results/limit explicitly AND the
query is attention-filtered (unread_only or unresponded_only), use a much
higher ceiling (_ATTENTION_QUERY_MAX_RESULTS) instead of the plain-listing
default. An explicit max_results/limit is still honored exactly as given,
and a plain unfiltered listing keeps the original default of 20 (avoiding
an unbounded dump of read mail for "show me my inbox"-type requests).

These tests avoid real IMAP: `_list_emails` is monkeypatched to record the
resolved `max_results` and return a small fixed result set.
"""
import pytest

pytest.importorskip("mcp")

import mcp_servers.email_server as es


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    for key in es._OWNER_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    es._ACCOUNT_CACHE.clear()
    # Single default account, no real DB/IMAP.
    monkeypatch.setattr(es, "_list_accounts_raw", lambda: [
        {"id": "acct1", "name": "default", "imap_user": "user@example.com", "is_default": True},
    ])
    monkeypatch.setattr(es, "_read_accounts_from_db", lambda: [
        {"id": "acct1", "name": "default", "imap_user": "user@example.com", "is_default": True},
    ])
    monkeypatch.setattr(es, "_load_config", lambda acct=None: {})
    yield
    es._ACCOUNT_CACHE.clear()


def _capture_list_emails(monkeypatch):
    calls = []

    def _fake_list_emails(folder="INBOX", max_results=20, unresponded_only=False,
                           unread_only=False, account=None):
        calls.append(max_results)
        return []

    monkeypatch.setattr(es, "_list_emails", _fake_list_emails)
    return calls


@pytest.mark.asyncio
async def test_unread_only_with_no_max_results_uses_attention_ceiling(monkeypatch):
    calls = _capture_list_emails(monkeypatch)
    await es.call_tool("list_emails", {"unread_only": True, es._MCP_OWNER_ARG: "tester"})
    assert calls == [es._ATTENTION_QUERY_MAX_RESULTS]


@pytest.mark.asyncio
async def test_unresponded_only_with_no_max_results_uses_attention_ceiling(monkeypatch):
    calls = _capture_list_emails(monkeypatch)
    await es.call_tool("list_emails", {"unresponded_only": True, es._MCP_OWNER_ARG: "tester"})
    assert calls == [es._ATTENTION_QUERY_MAX_RESULTS]


@pytest.mark.asyncio
async def test_plain_listing_with_no_max_results_keeps_default_of_20(monkeypatch):
    calls = _capture_list_emails(monkeypatch)
    await es.call_tool("list_emails", {es._MCP_OWNER_ARG: "tester"})
    assert calls == [20]


@pytest.mark.asyncio
async def test_explicit_max_results_is_honored_even_for_unread_only(monkeypatch):
    calls = _capture_list_emails(monkeypatch)
    await es.call_tool("list_emails", {"unread_only": True, "max_results": 3, es._MCP_OWNER_ARG: "tester"})
    assert calls == [3]


@pytest.mark.asyncio
async def test_explicit_limit_alias_is_honored_even_for_unread_only(monkeypatch):
    calls = _capture_list_emails(monkeypatch)
    await es.call_tool("list_emails", {"unread_only": True, "limit": 7, es._MCP_OWNER_ARG: "tester"})
    assert calls == [7]
