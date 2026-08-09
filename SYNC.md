# SYNC.md — Odysseus project sync bundle (2026-07-19)

Paste-ready, condensed sync for a fresh assistant with **no access to this machine or repo**.
Verified-not-assumed against the live repo/DB/git this session. Full detail lives in committed
`HANDOFF.md`, `AUDIT.md`, and `graphs/`. Four sections: (1) deployment + tool-calling,
(2) POODR design audit, (3) dependency graph, (4) churn/velocity. Consolidated
`UNVERIFIED / NEEDS INPUT` at the end.

---

## 0. BRANCH / REPO STATE (shared context)

- Branch **`fix/local-tool-calling`** @ `7ac20d6`, pushed to **`fork` = bstruong/odysseus**
  (`origin` = upstream `pewdiepie-archdaemon/odysseus`, UNTOUCHED, not merged to main).
- Commits: `009bcea` reliable native tool-calling; `2fbb5bd` supports_tools script + NOTES.md;
  `7b392da` web-intent tool-gating fix; `252f4ec` HANDOFF.md + AUDIT.md; `96da8b8` dep graphs (DOT);
  `7ac20d6` dep graphs (SVG). Committed docs: `HANDOFF.md`, `AUDIT.md`, `graphs/` (4 DOT + 4 SVG).
- Source is BAKED into the odysseus Docker image (only `data/`, `logs/` bind-mounted) → code changes
  need `docker compose build odysseus && docker compose up -d odysseus`.

---

## 1. DEPLOYMENT + LOCAL TOOL-CALLING  (detail: HANDOFF.md)

- Host "Metrotower": EndeavourOS/Arch, kernel 6.18.38-2-lts, RTX 3060 12288 MiB (driver 610.43.03),
  ~883 MiB idle. Odysseus via Docker Compose (odysseus/chromadb/searxng/ntfy).
- Models served by HOST Ollama (not Cookbook) at `OLLAMA_BASE_URL=http://host.docker.internal:11434/v1`.
  Endpoint row (data/app.db): id=a3c5a269, supports_tools=1, is_enabled=1.
- `OLLAMA_CONTEXT_LENGTH=16384` set (host systemd override; verified). Required — /v1 path sends no
  num_ctx; multi-round compound prompts hit 8–13k tokens and truncate at Ollama's ~4096 default.
- DEFAULT MODEL = **gemma4:e4b** (settings.json `default_model`/`research_model`; verified
  `resolve_endpoint("default")` -> gemma4:e4b). Switched from qwen3:8b (this doc's original default,
  see MODEL RESULTS below) in Phase 2 session 7, based on a cross-model benchmark (sessions 5-6:
  92% vs. 69% clean correctness across 13 task-instances, faster, lower VRAM) — see NOTES.md for the
  full evidence trail. qwen3:8b, llama3.1:8b, and granite4.1:8b (the other benchmark candidates) were
  removed from Ollama in session 8; only gemma4:e4b remains installed.
- The four fixes that made native tool-calling work on local models:
  1. supports_tools=1 (data/app.db, not git) — else tools_sent=0. Re-apply via
     scripts/set_ollama_supports_tools.py after any data-volume reset.
  2. llm_core.py: keep the date/time context a SEPARATE turn (merging it into the user request
     caused deterministic refusals).
  3. agent_loop.py: removed content keywords (note/todo/document/...) from _ADMIN_KEYWORDS — they
     flooded ~11 admin tools into the schema (dropped reliability to ~5%; removing -> ~100%).
  4. constants.py + llm_core.py: DEFAULT_TEMPERATURE 1.0 -> 0.2.
- Web search is PER-TURN opt-in (composer web toggle visibly ON, or /search <query>). Compound
  "search web AND save note" fixed in 7b392da (web-intent turns no longer strip content-write tools).
- MODEL RESULTS (measured this session; live only in transient files, not persisted in repo):
  qwen3:8b single 10/10, multi-step save 6/6, 0 fabrications even at ~13k tokens, peak VRAM 8.15 GB.
  qwen3:14b equal quality but 10.82 GB (over the ~10.5 GB Wayland ceiling). llama3-groq-tool-use:8b
  great single-tool, 0/6 multi-step. hermes3:8b weak. hermes4:8b does not exist in Ollama.
  manage_calendar sanity: qwen3:8b 6/6, correct relative-date resolution (skips list_calendars ->
  events go to default calendar; benign per src/tools/calendar.py:296-324).
- Backups: data/app.db.bak-supports_tools-20260715-215232, data/presets.json.bak-*, data/settings.json.bak-*.

---

## 2. POODR DESIGN AUDIT  (read-only; detail: AUDIT.md; scope src/ + routes/)

- VERDICT: hot path is PROCEDURAL (agent_loop.py/chat_routes.py/cookbook_routes.py = 0 classes each;
  ~650 module defs vs ~59 classes, many Pydantic/exception/dataclass). Service/manager layer is
  genuinely clean OO. Pain concentrated, not pervasive.
- Top findings: (1) SRP mega-functions: stream_agent_loop agent_loop.py:2547 (~1,934 lines);
  setup_email_routes email_routes.py:1110 (~4,100-line fn, 54 handlers in one closure);
  _stream_llm_inner llm_core.py:2126 (~620); chat_stream chat_routes.py:536 (~1,057).
  (2) Stringly-typed provider dispatch (biggest structural issue): _detect_provider llm_core.py:819
  returns a str tag re-opened at ~9 sites; CONFIRMED drift — _provider_label labels xAI/DeepSeek/
  Google/Together that _detect_provider doesn't recognize -> collapse to "openai". Refactor is a
  SEPARATE deliberate decision, NOT an audit action item. (3) No DB-session DI: 270 inline
  SessionLocal(), 0 Depends(get_db). (4) Inverted src->routes deps. (5) Leaky privates: _resolve_model
  (ai_interaction.py:76) imported 9 sites/7 modules; REALIZED latent bug: teacher_escalation.py:236
  imports _TEACHER_SYSTEM_PROMPT from ai_interaction where it no longer exists (moved to
  agent_tools/model_interaction_tools.py:20) -> ImportError when _call_teacher runs. STILL UNFIXED.
  (6) Demeter: request.app.state.auth_manager.<method>() 4-hop chains (chat_routes.py:936 etc).
- Done well (do NOT "fix"): MemoryProvider(ABC)+registry (is-a + composition); base-class-free
  agent_tools dict registry (duck typing); ChatGPTSubscription exception tree; agent_loop.py public
  surface (43 private/3 public, 0 leaks); no inheritance deeper than 2 levels; clean service classes
  (MemoryManager/RAGManager/McpManager/ToolIndex/ToolPolicy/EmbeddingClient).
- Highest-leverage refactors (each a deliberate choice, NOT started): (a) get_db session dependency
  -> migrate 270 SessionLocal(); (b) reverse src->routes imports; (c) Provider strategy object ->
  collapse the 9-site dispatch + kill the label/detect drift.

---

## 3. DEPENDENCY GRAPH  (mechanical: stdlib ast + Tarjan SCC; graphs/*.dot + *.svg; 192 modules, 605 edges)

- HEADLINE: ONE ~50-module strongly-connected component (26% of codebase) — hot path + tool subsystem
  + ~14 route modules all mutually reachable (why agent_loop/chat_routes changes ripple far). Plus 20
  direct A<->B mutual imports (endpoint_resolver<->llm_core, agent_loop<->tool_policy,
  agent_tools<->{tool_execution/implementations/parsing/schemas/security}, tool_implementations<->tools.*).
- Hubs: SAFE leaf hubs (high in / ~0 out): constants(46), auth_helpers(42), database(14). DANGEROUS
  (high in AND out): llm_core(30/8), tool_implementations(12/13), endpoint_resolver(25/5),
  ai_interaction(10/9). routes.prefs_routes in-degree 14 (a ROUTE depended on by src/).
- src->routes back-edges (corrects AUDIT.md's grep count of 11): AST-derived = 22 edges from 13 src/
  files, 21/22 INLINE (cycle-dodging): settings, caldav_sync, service_health, task_scheduler,
  builtin_actions, tools/*, etc.
- Service-layer isolation (SCC-verified): memory_provider/memory/rag_manager/mcp_manager/tool_index/
  embeddings are GENUINELY isolated (outside SCC, instantiated at app_initializer composition root).
  EXCEPTION: tool_policy — clean CLASS but tangled MODULE, pulled into the SCC via agent_loop.py:27
  (top import of ToolPolicy) <-> tool_policy.py:192 (inline import of agent_loop). See graphs/deps_hotpath.svg.

---

## 4. CHURN / VELOCITY  (from real git history; origin/main + origin/dev; repo NOT shallow)

- Project is YOUNG: first commit 2026-05-31 (~7 weeks). origin/dev is the DEFAULT/active branch
  (origin/HEAD->dev); main LAGS dev by 44 commits / 6 days (main 1893 commits @07-12; dev 1937 @07-18).
- VELOCITY (commits/ISO week; same on both branches): W22 initial import (+271k, exclude);
  W23 1005 | W24 395 | W25 196 | W26 178 | W27 110 | W28 37(dev)/8(main) | W29 15(dev only, 07-13..18).
  TREND: monotonic decline since the early-June W23 peak — ~1000/wk -> ~15/wk in ~6 weeks (order of
  magnitude). Confirmed genuine on dev (not a main-merge artifact). Monthly net: Jun +146k, Jul +36k(dev).
- WHERE code lands (both branches ~identical): static/ 224k >> tests/ 94k > src/ 82k > routes/ 67k.
  Heaviest files frontend/vendored/generated. CROSS-REF AUDIT.md: flagged mega-files are the
  highest-churn PYTHON source and still growing — tool_implementations.py(#6), cookbook_routes.py(#10),
  email_routes.py(#12), agent_loop.py(#13); llm_core.py(#28), chat_routes.py(#40) more moderate.
- CONTRIBUTORS: many-contributor OSS, one dominant lead — 330 authors (main)/342 (dev);
  pewdiepie-archdaemon 558 commits (~29%), long tail.
- OUR BRANCH vs upstream: 0 commits BEHIND origin/main (sits on main tip 9844a2f), 6 ahead. 44 BEHIND
  origin/dev; those dev-ahead commits touch ALL 4 files we modified — agent_loop.py(4), chat_routes.py(4),
  llm_core.py(3), constants.py(2). dev has web-search/_explicit_web_intent commits in chat_routes.py
  (SAME area as our 7b392da) -> expect conflicts there when main catches up to dev / if we rebase onto dev.

---

## UNVERIFIED / NEEDS INPUT (consolidated)

- Model result numbers (Section 1) are measured this session but live only in transient files, NOT
  persisted in the repo; the one real-world fabrication seen was n=1 (controlled 12/12 clean).
- VRAM budget ~10,500/~9,700 MiB is user-stated, not machine-measured. hermes3/llama3-groq VRAM figures
  are benchmark-window (possibly keep-alive-inflated), not clean-isolated.
- Audit line numbers are mostly spot-verified; high-stakes ones (provider drift, email god-func,
  teacher ImportError, 270 SessionLocal, _resolve_model 9 sites, tool_policy<->agent_loop cycle) were
  personally verified. Inline-import total (~1,300) is estimated; pattern verified.
- teacher_escalation.py:236 ImportError is a latent runtime bug found during a DESIGN audit (not a bug
  hunt) — STILL UNFIXED; decide standalone fix vs fold into a _resolve_model public-rename cleanup.
- Churn = added+removed lines (not net-new); high churn on a big file can be a few large edits. W22's
  +271k is the initial import. WHY velocity is slowing was NOT investigated (interpretation, not data).
- None of the audit/graph refactors have been done — analysis only. Confirm scope before any refactor.
```

---

## 5. REAL-USAGE EVALUATION  (2026-07-20; ran real tasks, not synthetic)

Question: is Odysseus-on-qwen3:8b good enough for real usage? Ran three real tasks in the app
(driven via UI; observed logs + real artifacts). No real email/calendar creds (deliberate).

- **Drafting (recruiter-email reply) = GENUINE WIN.** Real 467-char draft, all asks, concise, did
  NOT fabricate background (used "[Your Name]" placeholder). Send-ready with light edits.
- **Research via agent (Intel Arc Pro B70 -> document) depends entirely on WEB GROUNDING, not the
  model.** Web ON: accurate — but accuracy comes from the chat PRE-SEARCH injection, NOT model
  memory; with the grounding directive it also cites 4 real, verified URLs. Web OFF: model
  CONFABULATES a wholly wrong spec sheet (CUDA, 16GB, "2023") vs the real card (32GB/Battlemage/2026,
  no CUDA). qwen3:8b does NOT actually know recent products.
- **Deep Research feature = grounded but MEDIOCRE.** Real pipeline (5 rounds, 44 URLs, 26 cited
  sources) but ran on hermes3:8b, ~7 min, weak source curation (cryptobriefing.com for inflation;
  skipped bls.gov), meta-text leakage. Must-verify starting point only.
- **Fabrication event (~11.5k tokens, prior session): NOT reproduced** (session reached 14.3k tokens,
  create_document fired correctly both times). Left GENUINELY OPEN, not closed.
- **Compare + Documents editor: NOT exercised** — unevaluated this session.

CORRECTED OVERCLAIMS (honesty — the web-off test caught them): I first called the B70 doc "provably
fabricated" (WRONG — specs+benchmarks are real 2026 data past my Jan-2026 cutoff), then "the model
knew it from memory" (ALSO WRONG — web-off proves it doesn't; accuracy was pre-search). Truth:
research accuracy rides on web-grounding; qwen3:8b's memory of recent things is unreliable.

FIX DEPLOYED — commit `e6e7680` (pushed to fork): one base-rule bullet in `_API_AGENT_RULES`
(src/agent_loop.py): before writing researched facts/specs/latest info into a document/note/answer,
gather with a tool FIRST (web_search / trigger_research) and include source URLs. Verified: web-ON
cited 4 real URLs; web-OFF N=6 -> 0/6 fabricated sources, 5/5 routed to trigger_research (no
cite-washing). Its demonstrated effect is CITATIONS; grounding itself rides on pre-search (web on).

VERDICT (specific): transform/draft content you GIVE it = reliably helpful (daily-use win);
find/synthesize EXTERNAL facts = usable ONLY with web on (pre-search) or Deep Research — keep web ON
for any research/"latest"/product-spec task.

OPS: API tokens are Bearer "ody_" (bcrypt, api_tokens table) but gated to scope-aware API routes, not
interactive chat (minted+deleted one during eval; chat driven via UI). Branch @ e6e7680 on
fork=bstruong/odysseus; origin untouched.

UNVERIFIED (this section): fabrication event unresolved/not-reproduced (not "fixed"); Deep Research
source-quality weak + ran on hermes3:8b; Compare + Documents editor never exercised; rates are
small-sample (harness N<=6; web-off 1 timeout -> 5/6); web-off is a harness approximation of the
app's gating.

---

## 6. EMAIL / CALENDAR INTEGRATION BLOCKERS  (2026-07-20; code-level, NO real creds touched)

Priority use cases: multi-account Gmail, multi-calendar Google Calendar, web search, deep research.
Checked read-only whether Google Calendar + Gmail are actually connectable before wiring real accounts.

CALENDAR (Google Calendar) — NOT blocked; workable with setup friction.
- Odysseus calendar is CalDAV-ONLY (no OAuth path; account creds = URL+username+password, stored
  encrypted in prefs `caldav_accounts` LIST). Google CalDAV still works 2026: URL
  `https://apidata.googleusercontent.com/caldav/v2/<email>/events` + App Password (requires 2FA on;
  old google.com/calendar/dav is deprecated).
- MULTI-ACCOUNT calendar: YES (caldav_accounts is a list; sync_caldav loops all accounts).
- MULTI-CALENDAR within one Google account: code does principal->calendars() discovery (one
  CalendarCal per calendar), BUT caldav_sync.py:186-202 ITSELF notes Google's principal->home-set
  discovery "does not reliably enumerate calendars" and falls back to the single events URL. Practical
  upshot: for Google you likely must add each calendar's CalDAV URL manually
  (primary=/caldav/v2/<email>/events; secondary=/caldav/v2/<calendar_id>@group.calendar.google.com/events).

GMAIL — NOT blocked; use IMAP App-Password (OAuth is NOT configured).
- Auth: code supports BOTH Google OAuth (XOAUTH2) and IMAP/SMTP app-password. BUT OAuth is NOT set up:
  GOOGLE_OAUTH_CLIENT_ID/SECRET/REDIRECT_URI are UNSET in .env AND the running container (verified) ->
  the Sign-In flow 400s ("GOOGLE_OAUTH_CLIENT_ID not set — add it to .env", email_routes.py:5112).
  => working path today = imap.gmail.com:993 / smtp.gmail.com:465 + 16-digit App Password (needs 2FA).
- MULTI-ACCOUNT Gmail: YES (email_accounts table, per-account creds + is_default; pollers iterate .all()).

AUTO-SEEDED SCHEDULER TASKS (11) — safe to connect; nothing auto-runs.
- All SIX email/calendar tasks ship PAUSED (ship_paused=True) -> connecting Gmail/calendar triggers nothing.
- draft_email_replies = SAFE: LLM-drafts replies, INSERTs into LOCAL email_ai_replies table for review;
  NO SMTP send, nothing to sender (email_pollers.py:526).
- extract_email_events = the ONE that takes real action: auto-creates calendar events (create_event ->
  local + CalDAV write-back if a calendar is connected). Keep paused until trusted.
- summarize_emails / check_email_urgency = read + LOCAL store (tags in local email_tags table, NOT Gmail
  labels); can send digest/urgency-alert email to your OWN address only. email_auto_translate/classify_events
  = local only. NO task sends to senders or mutates the Gmail server. IMAP +FLAGS (delete/read/answered)
  are all USER-driven UI actions, not automations.
- The 5 "active" tasks (tidy_sessions/documents/research, consolidate_memory, audit_skills) = internal
  housekeeping on local data, event-triggered, never touch email/calendar.

NEEDS REAL-CRED TEST (can't confirm from code): (1) Odysseus CalDAV sync/write-back vs Google specifically;
(2) how many calendars Google's principal returns per account; (3) Gmail IMAP app-password end-to-end.
COMMON STEP: enabling 2FA once covers BOTH Gmail IMAP app-password AND Google Calendar CalDAV app-password.
