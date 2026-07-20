# Odysseus — Local Tool-Calling Handoff

Ground-truth handoff for a fresh assistant with **no access to this machine or repo**.
Every fact below was verified against the live system/DB/git on **2026-07-19** unless
explicitly marked otherwise. Items that could not be verified are listed at the end.

---

## 1. SETUP (verified)

- **Host:** EndeavourOS (Arch-based), kernel `Linux 6.18.38-2-lts x86_64`.
- **GPU:** NVIDIA GeForce RTX 3060, **12288 MiB** total, driver `610.43.03`. Idle GPU
  usage (desktop/Wayland) at check time: **883 MiB**.
- **Deployment:** Docker Compose. Containers running: `odysseus-odysseus-1`,
  `odysseus-chromadb-1`, `odysseus-ntfy-1`, `odysseus-searxng-1` (searxng healthy).
- **Source is BAKED into the odysseus image** — only `data/` and `logs/` are bind-mounted.
  Any code change requires: `docker compose build odysseus && docker compose up -d odysseus`.
- **Model backend:** the HOST's own Ollama (NOT Odysseus's Cookbook), reached at
  `OLLAMA_BASE_URL=http://host.docker.internal:11434/v1` (OpenAI-compatible `/v1` path).
- **Ollama endpoint row** (`data/app.db`, table `model_endpoints`):
  `id=a3c5a269`, `base_url=http://host.docker.internal:11434/v1`, `supports_tools=1`,
  `is_enabled=1`.
- **Default model** (`data/settings.json`): `default_model=qwen3:8b`,
  `default_endpoint_id=a3c5a269`, `utility_model=""` (empty → inherits the default).
  Verified `resolve_endpoint("default")` → `qwen3:8b @ …/v1/chat/completions`.
- **`OLLAMA_CONTEXT_LENGTH=16384`** — VERIFIED by reading the drop-in directly:
  `/etc/systemd/system/ollama.service.d/override.conf` contains both
  `OLLAMA_HOST=0.0.0.0:11434` and `OLLAMA_CONTEXT_LENGTH=16384`; both are present in the
  effective unit environment. This is required: the `/v1` path does not send `num_ctx`,
  and multi-round compound prompts reach 8–13k tokens; at Ollama's ~4096 default the
  prompt truncates and tool-calls get dropped.
- **VRAM budget:** USER-STATED target (not a machine-measurable fact): keep model+KV
  under ~10,500 MiB total (~800–900 MiB desktop baseline → ~9,700 MiB for model+context)
  to avoid Wayland compositor stutter.

## 2. FIX BRANCH STATE (verified via git)

- Current branch: **`fix/local-tool-calling`**.
- Commits on the branch (over `main`), newest first:
  - `7b392da` fix(chat): keep content-write tools available on web-intent turns
  - `2fbb5bd` chore: idempotent supports_tools script + local deployment notes
  - `009bcea` fix: reliable native tool-calling for local models (Ollama /v1)
- `git status`: clean working tree; branch is **in sync with `fork/fix/local-tool-calling`**
  (local HEAD `7b392da` == remote `fork` HEAD).
- **Remotes:** `fork` = `git@github.com:bstruong/odysseus.git` (user's fork, branch pushed
  here); `origin` = `https://github.com/pewdiepie-archdaemon/odysseus.git` (upstream,
  UNTOUCHED — nothing pushed there). Branch is **not** merged to `main`.

## 3. EACH FIX (described from the real diffs)

**`009bcea`** — `src/agent_loop.py`, `src/constants.py`, `src/llm_core.py` (+45/-8):
- `agent_loop.py`: removed content-tool keywords (`note/notes/todo/todos/reminder/
  reminders/document/documents/doc/docs/library/tidy`) from `_ADMIN_KEYWORDS`. They tripped
  `_detect_admin_intent`, which unions the entire `_ADMIN_TOOLS` set into the turn's
  schema list (~25 tools). That flood made local models omit required args or refuse
  (measured 5% success); those tools already reach the prompt via `_DOMAIN_TOOL_MAP` + RAG.
- `constants.py` + `llm_core.py`: `DEFAULT_TEMPERATURE` `1.0 → 0.2` (both the module
  constant and `LLMConfig`) for local tool-call argument fidelity.
- `llm_core.py`: added `_is_ephemeral_context_content()` and OR-ed it into the
  consecutive-user-message merge, so the injected date/time context stays a **separate
  turn** (behind an assistant boundary) instead of being merged into the user request.
  The merge previously buried the ask under ~750 chars of date/calendar boilerplate and
  caused deterministic refusals.

**`2fbb5bd`** — `scripts/set_ollama_supports_tools.py` (+102), `NOTES.md` (+45):
- `scripts/set_ollama_supports_tools.py`: stdlib-only, idempotent script that sets
  `supports_tools=1` on the local Ollama endpoint(s) in `data/app.db` (writes a `.bak`
  first). Re-run after any data-volume reset — the flag is not in git.
- `NOTES.md`: local-deploy guardrails (rebase fix branch before pulling; re-run the
  script after a DB reset; rebuild image after code changes; web-search opt-in; VRAM note).

**`7b392da`** — `routes/chat_routes.py` (+9/-5):
- In the `_explicit_web_intent` block, removed `create_document/edit_document/
  update_document/manage_notes/manage_calendar/manage_tasks` from the set stripped on
  web-classified turns. Those content-write tools are only surfaced by their own
  domain/RAG selection (never for a pure lookup), so keeping them available makes
  compound "search the web AND save as a note" complete in one turn. Genuine drift risks
  (`bash/python`, file, `send_email/reply_to_email`, `manage_memory/search_chats/
  manage_skills`, `api_call/builtin_browser`) are STILL stripped (verified at line ~899).

## 4. CURRENT MODEL RESULTS

Source: this session's benchmark harness runs (2026-07-19). These numbers were **measured
this session** but exist only in transient task-output files, **not persisted in the repo**.
Conditions: Ollama endpoint, 16k context, temp 0.2, 10-tool compound schema, real SearXNG.

Main benchmark — `N_single=10`, `N_multi=6`, multi ran at ~5k peak tokens:

| Model | single | multi-saved | own web_search+saved | fabricated | peak tok |
|---|---|---|---|---|---|
| qwen3:8b | 10/10 | 6/6 | 5/6 | 0/6 | 4885 |
| qwen3:14b | 10/10 | 6/6 | 4/6 | 0/6 | 4960 |
| llama3-groq-tool-use:8b | 10/10 | 0/6 | 0/6 | 0/6 | 4695 |
| hermes3:8b | 1/10 | 1/6 | 0/6 | 1/6 | 4301 |

11k-token heavy stress — `N=6`, real fetched page bodies, ~13k peak:

| Model | saved | own web_search+saved | fabricated | peak tok |
|---|---|---|---|---|
| qwen3:8b | 6/6 | 6/6 | 0/6 | 13383 |
| qwen3:14b | 6/6 | 5/6 | 0/6 | 13392 |

Peak VRAM @16k context:

| Model | peak VRAM | measurement quality |
|---|---|---|
| qwen3:8b | **8152 MiB** | CLEAN isolated measurement |
| qwen3:14b | **10819 MiB** | CLEAN isolated measurement |
| hermes3:8b | ~7500 MiB | benchmark-window only; may be keep-alive-contaminated |
| llama3-groq-tool-use:8b | ~6400 MiB | benchmark-window only; may be keep-alive-contaminated |

`manage_calendar` sanity (qwen3:8b, N=6, this session, terminal-only — not saved to a file):
called 6/6, created valid events 6/6, correct relative-date resolution
(e.g. "tomorrow 3pm" → `2026-07-20T15:00:00`), `list_calendars` first 0/6.

Notes:
- `hermes3:8b`'s single 1/10 here CONTRADICTS a prior-session measurement of 20/20 (that
  was a different, notes-only tool set). The discrepancy is real but not root-caused;
  suspected sensitivity to the web+notes tool mix. Treat hermes3 as unreliable here.
- `hermes4:8b` does NOT exist in the Ollama library (`pull … : file does not exist`).
- Prior-session single-run numbers (e.g. qwen3:14b "73%") were under different conditions
  and are NOT reflected in this table.

**Conclusion (backed by the above):** `qwen3:8b` is the best local model — matches/beats
qwen3:14b on quality, 0 fabrications even at ~13k tokens, and fits VRAM (8.15 GB vs the
14b's 10.82 GB, which exceeds the ~10.5 GB budget). It is already set as the default.

## 5. OPEN BUGS / ISSUES (with confidence)

There are **no confirmed open Odysseus *code* bugs** as of this session. Remaining items are
model-behavior observations:

- **Fabricated save on a large-context multi-step turn** — CONFIDENCE: observed **once**,
  in a real UI run (a "Search … Bitcoin … save as note" request at ~11.5k tokens printed
  "Note created: …" with a fabricated UUID and made **no** `manage_notes` call; no note was
  created). NOT reproduced in controlled testing: the 11k heavy-stress run was 0/6
  fabrications for both qwen models (12/12 clean across regimes). Assessed as a likely
  **n=1 sampling fluke**, not systematic. No specific code location — it is the model
  dropping the final tool call, not an Odysseus code defect.
- **llama3-groq-tool-use:8b cannot chain** — CONFIRMED (measured 0/6 multi-step, 10/10
  single). Model limitation, not an Odysseus bug.
- **hermes3:8b weak/inconsistent here** — CONFIRMED measured (1/10 single, 1/6 multi),
  cause SUSPECTED (tool-set sensitivity). Model behavior, not an Odysseus bug.

## 6. BACKUPS ON DISK (verified `ls`, 2026-07-19)

- `data/app.db.bak-supports_tools-20260715-215232` (618k, Jul 15)
- `data/presets.json.bak-222434` (1.8k, Jul 15)
- `data/settings.json.bak-132854` (2.6k, Jul 19)

## 7. GROUND RULES

- High-trust dev machine, but still prefer **reversible** changes and **confirm before
  anything destructive or outward-facing** (pushes, forks, deletes).
- Stay on `main` + the `fix/local-tool-calling` branch — **not `dev`**.
- **Never commit `.env`, `data/`, or `logs/` to any remote** (they are gitignored; keep it
  that way).
- Any editor command handed to the user must open **NeoVim (`nvim`)**, never nano — e.g.
  `sudo SYSTEMD_EDITOR=nvim systemctl edit <unit>`, `GIT_EDITOR=nvim`, `EDITOR=nvim`.

## 8. NEXT STEPS

- **Stage 5 — email/calendar integration.** qwen3:8b is the default and has passed notes,
  web-search, and calendar sanity checks.
- **Watch-item A — email tool gating (VERIFIED in code):** `reply_to_email`/`send_email`
  are stripped on web-intent turns (`routes/chat_routes.py:~899`) AND when an email reader
  is active (`routes/chat_routes.py:~920`, which also strips the `mcp__email__*` variants
  and `create_document`); in the active-email case the only compose path is
  `ui_control open_email_reply`. So an "email tool unavailable" symptom is most likely one
  of these gates, not a regression.
- **Watch-item B — calendar `list_calendars` pre-step (VERIFIED in code, BENIGN):**
  qwen3:8b skips the schema-recommended `list_calendars` call and goes straight to
  `create_event`. `src/tools/calendar.py:296–324` shows `create_event` falls back to
  `_ensure_default_calendar(db, owner)` when `calendar_href`/`calendar` is absent, and it
  also accepts a calendar *name* or short-id prefix. So events land on the default
  calendar; this is expected behavior, NOT a bug. Only relevant if multiple calendars exist
  and a specific one must be targeted (name it in the request).
- **Watch-item C (guidance):** the consolidated multi-action schema pattern
  (`manage_calendar/manage_tasks`, and any new email tool) is what qwen3:8b handled well
  after the admin-flood fix — do NOT re-add content/email keywords to `_ADMIN_KEYWORDS`.

---

## UNVERIFIED / NEEDS INPUT FROM USER

- **VRAM budget (~10,500 / ~9,700 MiB):** user-stated target, not machine-measured. Confirm
  the exact ceiling you want enforced.
- **hermes3 / llama3-groq peak VRAM (~7500 / ~6400 MiB):** benchmark-window figures, may be
  inflated by Ollama keep-alive overlap; NOT clean-isolated. Re-measure in isolation if a
  precise number matters (they are not the recommended model, so likely moot).
- **Model result numbers are not persisted in the repo** — they live only in this session's
  transient task-output files. If you want them retained, ask to have them written to a
  results file and committed.
- **`manage_calendar` sanity (6/6) and the single real-world fabrication** were observed in
  this session's terminal/UI only — no saved artifact. Re-run if you need a durable record.
- **The one real-world fabrication** was n=1; if large-context reliability is critical for
  Stage 5, a larger real-UI multi-step sample would firm up the "sampling fluke" assessment.
- **Prior-session (2026-07-15/16) numbers** referenced anywhere else were under different
  harness conditions and should not be mixed with the Section 4 table.
