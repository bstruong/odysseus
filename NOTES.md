# Local deployment notes (Metrotower — all-local, host Ollama)

This checkout carries local fixes that make native agent tool-calling work on
local models (Ollama `/v1`). They live on branch **`fix/local-tool-calling`**.

## Before you `git pull` / update `main`

1. **Rebase the fix branch, don't lose it.** The tool-calling fixes are on
   `fix/local-tool-calling`, not on `main`. After pulling `main`:
   ```
   git checkout fix/local-tool-calling
   git rebase main
   ```
2. **Re-apply the `supports_tools` DB flag.** It lives in `data/app.db` (not git),
   so a data-volume reset drops it. Re-run:
   ```
   python3 scripts/set_ollama_supports_tools.py
   ```
   (idempotent — safe to run any time; run it *after* the Ollama endpoint is
   registered in the UI).
3. **Rebuild the image after any code change.** Source is baked into the image
   (only `data/` and `logs/` are bind-mounted):
   ```
   docker compose build odysseus && docker compose up -d odysseus
   ```

## What the fixes do (see commit on `fix/local-tool-calling`)

- `data/app.db` — `ModelEndpoint.supports_tools=1` on the Ollama endpoint so native
  schemas are actually sent (else `tools_sent=0`). Applied by the script above.
- `src/llm_core.py` — keep the ephemeral date/time context a separate turn instead
  of merging it into the user request (the merge caused deterministic refusals).
- `src/agent_loop.py` — removed content keywords (note/todo/document/…) from
  `_ADMIN_KEYWORDS` so a plain "create a note" no longer floods ~11 admin tools into
  the schema (that flood dropped local tool-call reliability to ~5%; removing it
  restores ~100%). Those tools still reach the prompt via `_DOMAIN_TOOL_MAP` + RAG.
- `src/constants.py` / `src/llm_core.py` — `DEFAULT_TEMPERATURE` 1.0 → 0.2 for local
  tool-call argument fidelity.

## Known bug — 5 of 14 builtin email tools are unreachable (found during Step 3 model eval, not yet fixed)

**Symptom:** `search_emails` has never been called, ever, on this deployment —
confirmed via `docker compose logs odysseus | grep -c search_emails` returning `0`
across the full retained log history (every session, every prompt). A direct test
("Search my email for saber.") got 0 tool calls; the model's own reply said no
email-search tool was available in its function set. Separately, "draft a reply to
the email subject line X saying Y" (no UID/address given) got 0 tool calls too —
the model asked the user for the recipient's email address instead of looking the
email up, because the non-sending draft-reply tools it needed weren't available
either (see below) — it only had `reply_to_email` (send-immediately, though gated),
which needs a resolved recipient it never tried to resolve via `list_emails`
(which *was* available — that half is a separate, real model/strategy gap, not a
tool-availability one).

**Root cause:** every layer that decides which tools the model can see this round
— the system prompt (`AGENT_SYSTEM_PROMPT = _assemble_prompt(set(TOOL_SECTIONS.keys()))`),
the RAG-based `[tool-rag]`/`relevant_tools` retrieval, and the final
`selected_tools` list — builds its candidate universe from `TOOL_SECTIONS.keys()`
(`src/agent_loop.py`). A builtin email tool with no entry there is invisible at
every stage, regardless of query phrasing or model. Checked all 14 names in
`tool_security.BUILTIN_EMAIL_TOOLS` against `TOOL_SECTIONS` — **5 are missing**:

```
MISSING: search_emails
MISSING: draft_email
MISSING: draft_email_reply
MISSING: ai_draft_email_reply
MISSING: download_attachment
```

All 5 are fully implemented in `mcp_servers/email_server.py`, correctly registered
with the MCP protocol, and correctly classified as privileged/read-only-or-not in
`src/tool_security.py` — they're just never offered to the model. Notably this
knocks out *both* non-sending reply-drafting tools (`draft_email_reply`,
`ai_draft_email_reply`), leaving `reply_to_email` (which actually sends, modulo the
`agent_email_confirm` gate) as the only reply tool the model can ever reach.
`tests/test_email_registry_sync.py:54` already lists `search_emails` in a
`readonly` set, i.e. an existing test assumes it's a normal working tool — worth
checking whether that test (or a sibling) should have caught missing
`TOOL_SECTIONS` entries and currently doesn't.

**Practical effect:** "find/search my email for X" silently falls back to the
model improvising over `list_emails` and narrating that as a search (0/4 hit rate
observed against real, findable emails in Step 3's Task C). "Draft a reply to X"
with no email address handy has no safe, non-sending tool to reach for at all.
"Download the attachment from X" and "draft a new email" (without sending) are
presumably similarly broken, though not directly observed this session.

**Proposed fix (not yet implemented):** add `TOOL_SECTIONS` entries for all 5,
matching the style/format of the existing email-tool entries (JSON-args example,
one-line usage guidance). Also worth a look, once reachable: `_search_emails`'s
IMAP query construction (`FROM/SUBJECT/TEXT "<entire query>"` as one literal
phrase, not per-term OR) — a secondary, real issue that couldn't be observed in
practice until the tool is callable at all.

**Test plan (not yet written):** a registry-sync test asserting every name in
`tool_security.BUILTIN_EMAIL_TOOLS` has a corresponding `agent_loop.TOOL_SECTIONS`
entry (fail-loud so this class of gap can't recur silently — would have caught all
5 at once), plus an end-to-end check that a search-intent and a draft-reply-intent
prompt each actually surface the right tool in `relevant_tools`/`selected_tools`.

**Status: implemented and tested locally, not yet upstreamed.**

The fix initially shipped as TOOL_SECTIONS-only, was rebuilt/deployed, and
re-tested live — `search_emails` was STILL unreachable (`relevant_tools`
still excluded it for "Search my email for saber."). Root cause of the gap:
`mcp_manager.get_tool_descriptions_for_prompt()` explicitly skips every
builtin MCP server's tools when building the embedding corpus used for
semantic tool retrieval ("they're already in the agent prompt") — so
`ToolIndex.retrieve()` can never surface a builtin email tool by embedding
similarity, full stop. The actual mechanism that makes `list_emails`,
`archive_email`, etc. reachable for an "email"-flavored query is a second,
separate hardcoded list: `ToolIndex._KEYWORD_HINTS` in `src/tool_index.py`,
which has the *same* gap TOOL_SECTIONS had. Fixing TOOL_SECTIONS alone was
necessary (system-prompt documentation) but not sufficient (reachability) —
both had to be fixed together. Caught by re-verifying against the live
container after the first rebuild rather than trusting the unit tests alone.

Three changes now:

- `src/agent_loop.py` — added `TOOL_SECTIONS` entries for all 5 previously-missing
  tools (`search_emails`, `draft_email`, `draft_email_reply`, `ai_draft_email_reply`,
  `download_attachment`), matching the existing entries' style.
- `src/tool_index.py` — added the same 5 tools to `ToolIndex._KEYWORD_HINTS`'s
  email-flavored entry (the frozenset keyed on "email"/"mail"/"reply"/etc.) — this
  is the one that actually controls per-round tool availability for builtin email
  tools.
- `mcp_servers/email_server.py` — added `_build_imap_search_query()` and wired
  `_search_emails` to use it: splits the query into terms, drops a small stopword
  list and per-term punctuation, then ANDs per-term OR-of-FROM/SUBJECT/TEXT clauses
  (IMAP ANDs sibling search keys implicitly). Falls back to the unfiltered/raw
  terms if stopword-filtering or punctuation-stripping would otherwise empty the
  query, so a query can never degenerate into an empty/invalid IMAP command.
- Tests: `tests/test_email_tool_sections_registry_sync.py` (asserts every name in
  `tool_security.BUILTIN_EMAIL_TOOLS` is in BOTH `TOOL_SECTIONS` and
  `_KEYWORD_HINTS`'s email entry — fails loudly if either regresses for any future
  email tool) and `tests/test_search_emails_term_matching.py` (unit tests on
  `_build_imap_search_query` plus one integration test confirming `_search_emails`
  actually sends the term-AND query, not a literal phrase, to IMAP). Full suite:
  4561 passed, 3 skipped, 0 failed (baseline was 4537 before tonight).

**Not done:** a live-container end-to-end test is what actually caught the
`_KEYWORD_HINTS` gap the unit tests couldn't — there's no automated version of
that check in the suite yet (it needs the running ChromaDB-backed pipeline).
The registry-sync test now covers both known reachability mechanisms directly,
but "reachable per these two mechanisms" and "actually offered by the live
pipeline" were proven different once already this session, so treat a second
live re-verification after the next rebuild as required, not optional.

Still separate scope, left alone as instructed: the `agent_email_confirm` gate fix
(implemented earlier, also not yet upstreamed) and the `reply_to_email` \Answered
bug (confirmed present, intentionally not fixed this pass).

Requires an image rebuild to actually run (source is baked in, see "Before you
`git pull`" above) — that rebuild will also be the first real-IMAP run of the
confirmation-gate fix, since both are on this branch now.

## Phase 2 session 4 — same bug family, third distinct location: FUNCTION_TOOL_SCHEMAS (native/API mode)

Session 3 found the same 5 tools (`search_emails`, `draft_email`, `draft_email_reply`,
`ai_draft_email_reply`, `download_attachment`) missing from `src/tool_schemas.py`'s
`FUNCTION_TOOL_SCHEMAS` — the only schema source `agent_loop.py` uses for
native/API-mode models (`supports_tools=1`, e.g. qwen3:8b in this deployment).
`mcp_manager.get_all_openai_schemas()` deliberately skips builtin MCP servers
(comment: "they use the code-block tool format" / "already in the agent prompt")
— confirmed intentional, not an oversight: the design puts `FUNCTION_TOOL_SCHEMAS`
as sole source of truth for builtin-tool schemas in native mode specifically to
avoid two hand-maintained copies disagreeing. So the fix belongs in
`FUNCTION_TOOL_SCHEMAS`, not in loosening that skip.

Added all 5 entries, each diffed field-for-field (properties + required) against
`mcp_servers/email_server.py`'s real `inputSchema` — confirmed exact match
programmatically, not hand-typed on faith. Did not add `additionalProperties: false`
to the new entries (that's a targeted fix scoped to `list_emails`'s query-smuggling
bug, not a house style — none of the other existing entries carry it).

**Found a fourth location for the same bug class while regression-testing:**
`src/tool_index.py`'s `BUILTIN_TOOL_DESCRIPTIONS` (the embedding corpus for
semantic RAG tool retrieval — separate from `_KEYWORD_HINTS`, which force-includes
by literal keyword match and already had all 5 tools since session 1) was also
missing all 5. An existing test (`tests/test_tool_index_schema_parity.py`, written
after an earlier `api_call` instance of this exact bug) caught it immediately once
`FUNCTION_TOOL_SCHEMAS` gained the entries. Fixed the same way — 5 entries added,
matching the file's existing terse style. Because `_KEYWORD_HINTS` already
force-includes all 5 for any "email/mail/reply/..." keyword match, this gap did not
block the literal Step 3 re-verification prompt below, but it did mean the 5 tools
were unreachable via pure semantic similarity for an email-flavored query that
doesn't hit the keyword list — a real, now-closed gap.

Also updated a stale comment in `src/tool_security.py` (`_PLAN_MODE_KNOWN_MUTATORS`)
that said these 5 tools "have no native schemas (yet)" — no longer true.

Full suite: 4573 passed, 3 skipped, 0 failed (baseline 4561 from session 3's last
run + 6 new test files added since).

**Live re-verification (2 fresh runs, real qwen3:8b, native tool-calling, real
account, read-only):** prompt "Search my email for saber." — both runs: 23 tools
sent (matches `relevant_tools` count exactly, i.e. all 5 previously-missing tools
made it through this time), model called `search_emails` directly on round 1 (no
`list_emails` fallback), exit_code=0, produced a correct final answer listing the
matching "saber" emails. Session 3's "invents a query argument on list_emails"
hypothesis is confirmed for this prompt: with `search_emails` actually offered,
qwen3:8b reaches for it correctly rather than smuggling a `query` param into
`list_emails`.

Running fix count in this working tree: 8 (session 1's TOOL_SECTIONS + _KEYWORD_HINTS
+ IMAP query-term fix; session 3's FUNCTION_TOOL_SCHEMAS/list_emails
additionalProperties fix; this session's FUNCTION_TOOL_SCHEMAS 5-tool addition +
BUILTIN_TOOL_DESCRIPTIONS 5-tool addition + tool_security.py comment fix), or 9
including the pre-existing `agent_email_confirm` gate. Not committed/pushed/upstreamed.

### Starting context for session 5 (do not re-derive)

- **Go/no-go: Step 4 (cross-model benchmark) is CLEAR TO RUN.** The
  FUNCTION_TOOL_SCHEMAS gap that made Steps 1-3 a NO-GO in session 3 is fixed
  and live-reverified (2/2 runs: `search_emails` offered + correctly chosen by
  qwen3:8b, no `list_emails` fallback). Nothing else surfaced this session that
  should hold it further.
- **All 4 known tool-registry sources are now in sync for the 5 email tools**
  (`search_emails`, `draft_email`, `draft_email_reply`, `ai_draft_email_reply`,
  `download_attachment`): `TOOL_SECTIONS` (agent_loop.py, session 1),
  `_KEYWORD_HINTS` (tool_index.py, session 1), `FUNCTION_TOOL_SCHEMAS`
  (tool_schemas.py, session 4), `BUILTIN_TOOL_DESCRIPTIONS` (tool_index.py,
  session 4). Four independent hand-maintained lists is itself the systemic
  risk — this is the fourth confirmed instance of one of them drifting out of
  sync with the others. No test currently guards all four against each other
  at once (only pairwise: `test_email_tool_sections_registry_sync.py` covers
  TOOL_SECTIONS+_KEYWORD_HINTS; `test_tool_index_schema_parity.py` covers
  FUNCTION_TOOL_SCHEMAS+BUILTIN_TOOL_DESCRIPTIONS). A combined 4-way sync test,
  or collapsing to fewer sources of truth, is flagged but deliberately not
  done — worth a dedicated session if this bug class recurs a fifth time.
- **Still open, still out of scope, still real:** the pre-existing
  `agent_email_confirm` gate fix and the `reply_to_email` `\Answered` bug
  (both from before session 1) — neither touched this session. The
  pending-actions approval UI (backend exists in `routes/email_routes.py`,
  no frontend) is also still unbuilt.
- **Working tree is still mixed and uncommitted** — 8 distinct fixes (9 with
  the confirm gate) sitting together, not split into separate PRs, not
  upstreamed. Splitting this remains a deliberately deferred decision, not
  an oversight.
- **Container state:** the odysseus image was rebuilt and restarted this
  session to bake in the session-4 fix for live re-verification — the running
  container reflects the current working tree, not a stale build.

## Operational notes

- **Web search is per-turn opt-in.** Enable the composer web toggle (visibly active)
  or use `/search <query>`. An unchecked toggle in agent mode sends an explicit deny.
- **VRAM budget** (RTX 3060 12GB): keep model + KV context under ~10,500 MiB total
  (desktop baseline ~800–900 MiB) to avoid Wayland compositor stutter.
