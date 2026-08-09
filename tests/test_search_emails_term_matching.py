"""Coverage for _build_imap_search_query / _search_emails term matching.

_search_emails used to build a single literal IMAP SEARCH phrase from the
whole free-text query (FROM/SUBJECT/TEXT "<entire query>"), which requires
an exact substring match. A natural-language query like "partnership idea
for my saber project" then fails against a real subject like "Partnership
idea on your saber project" — every meaningful word is present, but the
phrase as a whole isn't a substring. This was discovered because
search_emails was *also* unreachable from the agent (see
test_email_tool_sections_registry_sync.py) — once that's fixed, this is
what determines whether searching for something actually works.

Fix: split into terms, drop a small stopword list and per-term punctuation,
and AND per-term OR-of-field clauses together (IMAP ANDs sibling search
keys implicitly — no explicit AND operator needed).
"""
import pytest

pytest.importorskip("mcp")

import mcp_servers.email_server as es


# ── _build_imap_search_query: pure unit tests ────────────────────────────

def test_multi_word_query_becomes_and_of_per_term_or_clauses():
    cmd = es._build_imap_search_query("saber project")
    assert cmd == (
        '((OR OR FROM "saber" SUBJECT "saber" TEXT "saber") '
        '(OR OR FROM "project" SUBJECT "project" TEXT "project"))'
    )


def test_stopwords_are_dropped():
    cmd = es._build_imap_search_query("partnership idea for my saber project")
    # "for" and "my" must not appear anywhere in the built command.
    assert '"for"' not in cmd
    assert '"my"' not in cmd
    for term in ("partnership", "idea", "saber", "project"):
        assert f'"{term}"' in cmd


def test_trailing_punctuation_is_stripped_per_term():
    cmd = es._build_imap_search_query("saber project?")
    assert '"project?"' not in cmd
    assert '"project"' in cmd


def test_query_of_only_stopwords_falls_back_to_unfiltered_terms():
    # If filtering would remove every term, keep the originals rather than
    # emit an empty/invalid search command.
    cmd = es._build_imap_search_query("is the a")
    assert cmd != "()"
    assert '"is"' in cmd or '"the"' in cmd or '"a"' in cmd


def test_punctuation_only_query_does_not_produce_empty_command():
    cmd = es._build_imap_search_query("???")
    assert cmd != "()"


def test_single_term_query_matches_prior_single_literal_behavior():
    # For a one-word query, per-term AND/OR degenerates to the same shape
    # the old literal-phrase code produced.
    cmd = es._build_imap_search_query("saber")
    assert cmd == '((OR OR FROM "saber" SUBJECT "saber" TEXT "saber"))'


# ── _search_emails: confirms the built query is what's actually sent ────

class FakeSearchConn:
    def __init__(self):
        self.calls = []

    def select(self, folder, readonly=False):
        self.calls.append(("select", folder, readonly))
        return "OK", []

    def uid(self, command, *args):
        self.calls.append(("uid", command, *args))
        if command == "SEARCH":
            return "OK", [b""]  # no matches; we only care what was searched for
        return "OK", []

    def logout(self):
        self.calls.append(("logout",))


def test_search_emails_sends_the_term_and_query_not_a_literal_phrase(monkeypatch, tmp_path):
    # Isolate from this machine's real app.db (owner-scoped accounts would
    # otherwise make _load_config's owner-required check fire via the
    # cached-summaries lookup) — same pattern as test_email_action_confirm_gate.py.
    monkeypatch.setattr(es, "APP_DB", str(tmp_path / "app.db"))
    conn = FakeSearchConn()
    monkeypatch.setattr(es, "_imap_connect", lambda account=None: conn)
    monkeypatch.setattr(es, "_fixture_search_emails", lambda *a, **k: None)

    es._search_emails("partnership idea for my saber project", folders=["INBOX"])

    search_calls = [c for c in conn.calls if c[0] == "uid" and c[1] == "SEARCH"]
    assert len(search_calls) == 1
    sent_cmd = search_calls[0][3]
    assert sent_cmd == es._build_imap_search_query("partnership idea for my saber project")
    # The old behavior would have sent the whole phrase as one literal string;
    # confirm that's gone.
    assert 'FROM "partnership idea for my saber project"' not in sent_cmd
