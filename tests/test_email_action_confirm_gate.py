"""Confirmation-gate coverage for archive_email, delete_email,
mark_email_read, and bulk_email.

These four MCP email tools used to execute immediately against real IMAP
with no confirmation gate — only send_email/reply_to_email were gated
behind the `agent_email_confirm` setting (see _stash_agent_draft). This
closes that hole by extending the same setting/pattern to the four
mutating, non-send tools: when the gate is on, the tool call must stage
the action in `pending_email_actions` instead of touching IMAP, and must
require a separate, out-of-band approval (routes/email_routes.py's
/pending-actions endpoints) before anything happens for real.

Follows the monkeypatch style established in test_imap_mailbox_quoting.py.
"""
import json
import sqlite3

import pytest

pytest.importorskip("mcp")

import mcp_servers.email_server as es


@pytest.fixture(autouse=True)
def _clear_mcp_email_owner_env(monkeypatch):
    for key in es._OWNER_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    es._ACCOUNT_CACHE.clear()
    yield
    es._ACCOUNT_CACHE.clear()


@pytest.fixture
def pending_db(tmp_path, monkeypatch):
    db_path = tmp_path / "scheduled_emails.db"
    monkeypatch.setattr("src.constants.SCHEDULED_EMAILS_DB", str(db_path))
    # Isolate from this machine's real app.db (which may have real,
    # owner-scoped accounts configured) — a missing/empty DB here means
    # _read_accounts_from_db() safely returns [].
    monkeypatch.setattr(es, "APP_DB", str(tmp_path / "app.db"))
    return db_path


def _rows(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT * FROM pending_email_actions ORDER BY created_at"
        ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        # Table is created lazily on first stash; no rows staged == no table.
        return []
    finally:
        conn.close()


def _forbid_imap(monkeypatch):
    """Fail the test loudly if the gated path ever reaches real IMAP."""
    def _boom(*args, **kwargs):
        raise AssertionError("gated tool call touched IMAP — confirmation gate did not hold")
    monkeypatch.setattr(es, "_imap_connect", _boom)


# ── Gate ON (default): stage, never touch IMAP ───────────────────────────

@pytest.mark.asyncio
async def test_archive_email_stages_when_confirm_on(monkeypatch, pending_db):
    monkeypatch.setattr(es, "_read_agent_email_confirm_setting", lambda: True)
    _forbid_imap(monkeypatch)

    out = await es.call_tool(
        "archive_email", {"uid": "42", "folder": "INBOX", "_odysseus_owner": "tester"}
    )
    text = out[0].text

    assert "staged for your approval" in text
    assert "nothing has happened yet" in text

    rows = _rows(pending_db)
    assert len(rows) == 1
    assert rows[0]["action"] == "archive"
    assert rows[0]["uid"] == "42"
    assert rows[0]["status"] == "agent_pending"
    assert rows[0]["owner"] == "tester"


@pytest.mark.asyncio
async def test_delete_email_stages_when_confirm_on(monkeypatch, pending_db):
    monkeypatch.setattr(es, "_read_agent_email_confirm_setting", lambda: True)
    _forbid_imap(monkeypatch)

    out = await es.call_tool(
        "delete_email", {"uid": "7", "folder": "INBOX", "_odysseus_owner": "tester"}
    )
    assert "staged for your approval" in out[0].text

    rows = _rows(pending_db)
    assert rows[0]["action"] == "delete"
    assert rows[0]["permanent"] == 0


@pytest.mark.asyncio
async def test_delete_email_permanent_stages_and_flags_irreversible(monkeypatch, pending_db):
    monkeypatch.setattr(es, "_read_agent_email_confirm_setting", lambda: True)
    _forbid_imap(monkeypatch)

    out = await es.call_tool(
        "delete_email",
        {"uid": "7", "folder": "INBOX", "permanent": True, "_odysseus_owner": "tester"},
    )
    assert "staged for your approval" in out[0].text

    rows = _rows(pending_db)
    assert rows[0]["permanent"] == 1
    assert "CANNOT BE UNDONE" in (rows[0]["description"] or "")


@pytest.mark.asyncio
async def test_mark_email_read_stages_when_confirm_on(monkeypatch, pending_db):
    monkeypatch.setattr(es, "_read_agent_email_confirm_setting", lambda: True)
    _forbid_imap(monkeypatch)

    out = await es.call_tool(
        "mark_email_read",
        {"uid": "9", "read": False, "folder": "INBOX", "_odysseus_owner": "tester"},
    )
    assert "staged for your approval" in out[0].text

    rows = _rows(pending_db)
    assert rows[0]["action"] == "mark_email_read"
    assert rows[0]["read_flag"] == 0


@pytest.mark.asyncio
async def test_bulk_email_with_explicit_uids_stages_when_confirm_on(monkeypatch, pending_db):
    monkeypatch.setattr(es, "_read_agent_email_confirm_setting", lambda: True)
    _forbid_imap(monkeypatch)

    out = await es.call_tool(
        "bulk_email",
        {"action": "delete", "uids": ["1", "2"], "folder": "INBOX", "_odysseus_owner": "tester"},
    )
    assert "staged for your approval" in out[0].text

    rows = _rows(pending_db)
    assert rows[0]["action"] == "bulk_email"
    assert json.loads(rows[0]["uids"]) == ["1", "2"]
    assert rows[0]["bulk_action"] == "delete"


@pytest.mark.asyncio
async def test_bulk_email_all_unread_stages_without_resolving_uids(monkeypatch, pending_db):
    # all_unread=True would otherwise trigger an IMAP UNSEEN search before
    # the bulk mutation — that resolution must not happen while gated either,
    # since it still requires a live IMAP connection.
    monkeypatch.setattr(es, "_read_agent_email_confirm_setting", lambda: True)
    _forbid_imap(monkeypatch)

    out = await es.call_tool(
        "bulk_email",
        {"action": "delete", "all_unread": True, "permanent": True, "_odysseus_owner": "tester"},
    )
    assert "staged for your approval" in out[0].text
    assert "PERMANENT" in out[0].text or "cannot be undone" in out[0].text.lower()

    rows = _rows(pending_db)
    assert rows[0]["all_unread"] == 1
    assert rows[0]["permanent"] == 1


@pytest.mark.asyncio
async def test_bulk_email_no_targets_still_errors_before_staging(monkeypatch, pending_db):
    monkeypatch.setattr(es, "_read_agent_email_confirm_setting", lambda: True)
    _forbid_imap(monkeypatch)

    out = await es.call_tool(
        "bulk_email", {"action": "delete", "_odysseus_owner": "tester"}
    )
    assert "No messages selected" in out[0].text
    assert _rows(pending_db) == []


# ── Gate OFF: unchanged legacy behavior (regression) ─────────────────────

@pytest.mark.asyncio
async def test_archive_email_executes_immediately_when_confirm_off(monkeypatch, pending_db):
    monkeypatch.setattr(es, "_read_agent_email_confirm_setting", lambda: False)
    called = {}

    def _fake_archive(uid, folder, account=None):
        called["args"] = (uid, folder, account)
        return True

    monkeypatch.setattr(es, "_archive_email", _fake_archive)

    out = await es.call_tool(
        "archive_email", {"uid": "42", "folder": "INBOX", "_odysseus_owner": "tester"}
    )

    assert called["args"] == ("42", "INBOX", None)
    assert "Archived UID 42" in out[0].text
    assert _rows(pending_db) == []


@pytest.mark.asyncio
async def test_delete_email_executes_immediately_when_confirm_off(monkeypatch, pending_db):
    monkeypatch.setattr(es, "_read_agent_email_confirm_setting", lambda: False)
    called = {}

    def _fake_delete(uid, folder, permanent=False, account=None):
        called["args"] = (uid, folder, permanent, account)
        return True

    monkeypatch.setattr(es, "_delete_email", _fake_delete)

    out = await es.call_tool(
        "delete_email", {"uid": "7", "folder": "INBOX", "_odysseus_owner": "tester"}
    )

    assert called["args"] == ("7", "INBOX", False, None)
    assert "Deleted UID 7" in out[0].text


@pytest.mark.asyncio
async def test_mark_email_read_executes_immediately_when_confirm_off(monkeypatch, pending_db):
    monkeypatch.setattr(es, "_read_agent_email_confirm_setting", lambda: False)
    called = {}

    def _fake_set_flag(uid, folder, flag, add=True, account=None):
        called["args"] = (uid, folder, flag, add, account)
        return True

    monkeypatch.setattr(es, "_set_flag", _fake_set_flag)

    out = await es.call_tool(
        "mark_email_read", {"uid": "9", "folder": "INBOX", "_odysseus_owner": "tester"}
    )

    assert called["args"] == ("9", "INBOX", "\\Seen", True, None)
    assert "as read" in out[0].text


@pytest.mark.asyncio
async def test_bulk_email_executes_immediately_when_confirm_off(monkeypatch, pending_db):
    monkeypatch.setattr(es, "_read_agent_email_confirm_setting", lambda: False)
    called = {}

    def _fake_bulk_set_flag(uids, folder, flag, add=True, account=None):
        called["args"] = (uids, folder, flag, add, account)
        return len(uids)

    monkeypatch.setattr(es, "_bulk_set_flag", _fake_bulk_set_flag)

    out = await es.call_tool(
        "bulk_email",
        {"action": "mark_read", "uids": ["1", "2"], "folder": "INBOX", "_odysseus_owner": "tester"},
    )

    assert called["args"] == (["1", "2"], "INBOX", "\\Seen", True, None)
    assert "2 email(s) marked read" in out[0].text


# ── send_email / reply_to_email gate must be unaffected (regression) ────

@pytest.mark.asyncio
async def test_send_email_gate_still_stages_as_agent_draft(monkeypatch, pending_db):
    monkeypatch.setattr(es, "_read_agent_email_confirm_setting", lambda: True)

    def _boom_load_config(account=None):
        raise AssertionError("send_email must not resolve SMTP config beyond account lookup during staging")

    # _send_email still legitimately calls _load_config to resolve the
    # account before staging (see _send_email docstring) — only assert it
    # never reaches SMTP/IMAP.
    monkeypatch.setattr(es, "_smtp_connect", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("send_email touched SMTP while gated")))
    monkeypatch.setattr(es, "_imap_connect", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("send_email touched IMAP while gated")))

    result = es._send_email(to="a@example.com", subject="Hi", body="Body")

    assert result["pending"] is True
    assert result["success"] is True


@pytest.mark.asyncio
async def test_reply_to_email_answered_flag_set_even_when_reply_only_staged(monkeypatch, pending_db):
    """Reconfirms the separate, still-unfixed bug: reply_to_email marks the
    original message \\Answered even when the reply itself was only staged
    (agent_email_confirm on), not actually sent. Documented as a known,
    distinct issue in Step 2 of the confirmation-gate fix — intentionally
    NOT fixed by this change; this test only proves it is still present so
    it isn't silently fixed as a side effect of unrelated work."""
    monkeypatch.setattr(es, "_read_agent_email_confirm_setting", lambda: True)

    orig = {
        "Subject": "Hello",
        "Message-ID": "<orig@example.com>",
        "From": "sender@example.com",
    }
    import email as email_mod

    msg = email_mod.message.EmailMessage()
    for k, v in orig.items():
        msg[k] = v

    class _FetchConn:
        def select(self, folder, readonly=False):
            return "OK", []

        def uid(self, command, *args):
            if command == "FETCH":
                return "OK", [(b"1", msg.as_bytes())]
            return "OK", []

        def logout(self):
            pass

    monkeypatch.setattr(es, "_imap_connect", lambda account=None: _FetchConn())

    flagged = {}

    def _fake_set_flag(uid, folder, flag, add=True, account=None):
        flagged["called"] = (uid, folder, flag, add)
        return True

    monkeypatch.setattr(es, "_set_flag", _fake_set_flag)

    out = await es.call_tool(
        "reply_to_email",
        {"uid": "1", "body": "Thanks", "folder": "INBOX", "_odysseus_owner": "tester"},
    )

    # The reply itself was staged (pending), not sent...
    rows = _rows(pending_db)
    assert rows == []  # reply staging goes to scheduled_emails, not pending_email_actions
    # ...yet \Answered was still set on the original — the known secondary bug.
    assert flagged.get("called") == ("1", "INBOX", "\\Answered", True)
    assert "Replied to UID 1" in out[0].text
