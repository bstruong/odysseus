# POODR Design Audit — Odysseus (`src/` + `routes/`)

Read-only design-quality audit against Sandi Metz's *Practical Object-Oriented Design*
principles. Verified against live code on **2026-07-19**. Excludes the `fix/local-tool-calling`
tool-calling changes and the accepted tradeoffs documented in `HANDOFF.md`.

**Headline:** the manager/service layer is genuinely well-factored OO; the pain is concentrated
in a handful of procedural mega-functions, a stringly-typed provider/model dispatch, the total
absence of DB-session injection, and an inverted `src/ → routes/` dependency. This is a common
shape for a fast-moving Python app — **predominantly procedural on the hot path, real OO in the
service layer.**

---

## 1. Single Responsibility

Several module-level functions do 5–7 unrelated jobs — the classic "job description needs an *and*."
All **will cause pain as they grow**:

- `stream_agent_loop` — `src/agent_loop.py:2547` → **1,934 lines** (to EOF 4481). Merges schemas
  *and* streams the LLM *and* parses/resolves tool blocks *and* executes tools (~:3964) *and*
  enforces budget/stall/runaway *and* runs a verifier *and* computes metrics. Adding a tool means
  editing inside a 2k-line closure with no seam.
- `setup_email_routes` — `routes/email_routes.py:1110` → the whole module is **one ~4,100-line
  function** wrapping **54 route handlers** + an IMAP pool + 5 closure-local caches. A god-object
  built from closures; nothing inside is testable/reusable in isolation.
- `_stream_llm_inner` — `src/llm_core.py:2126` (~620 lines): provider dispatch + inline payload
  build + per-provider SSE parse + copy-pasted error→SSE mapping, fused.
- `chat_stream` — `routes/chat_routes.py:536` (~1,057): HTTP body parsing + intent-detection policy
  + context wiring + tool gating in one handler.
- `_build_system_prompt` — `src/agent_loop.py:1529` (~558): prompt assembly entangled with cache-key
  computation and Jaccard skill-retrieval.
- Also: `model_serve` `routes/cookbook_routes.py:1880` (761), `_list_emails_sync`
  `routes/email_routes.py:1436` (424), `TaskScheduler` god-object `src/task_scheduler.py:333`
  (36 methods; the delivery methods want their own object).

## 2. Dependency management

- **Inverted direction (`src/ → routes/`) — will cause pain.** **11** core files import from the web
  layer, e.g. `src/settings.py:291` → `from routes.prefs_routes import _load_for_user`,
  `src/caldav_sync.py:278` → `routes.calendar_routes`, `src/service_health.py:315` →
  `routes.email_helpers`. Stable domain code depends on volatile HTTP handlers; the
  inline-import-inside-try/except style is a tell that it's dodging the resulting cycles rather than
  fixing them.
- **No DB-session injection — will cause pain.** **270** inline `SessionLocal()` and **0**
  `Depends(get_db)` providers. E.g. `src/tools/notes.py:41`, `routes/document_routes.py` (24 sites).
  Sessions can't be swapped for a fake/transaction, so tools can't be unit-tested without
  monkeypatching a module global. `src/embeddings.py:45` (`EmbeddingClient`, injected
  url/model/key) is the good counter-template.
- **Hardcoded HTTP clients (minor→moderate):** `httpx.AsyncClient(...)` built inside methods —
  `src/ai_interaction.py:1012`, `src/integrations.py:458`, `src/tools/research.py:122` — no seam to
  stub network calls.
- **Inline imports (moderate):** dependencies hidden in function bodies rather than module headers
  (agent-estimated ~1,300; verified `from core.database` inline appears widely). Hides the true
  coupling surface and masks cycles (see the inverted-direction point).

## 3. Public vs. private interface

- **Leaky privates — moderate, systemic.** `_`-named symbols are de-facto cross-module public API.
  `_resolve_model` (`src/ai_interaction.py:76`) is imported at **9 sites / 7 modules**;
  `_detect_provider` at 5; `src/tools/_common.py` (an *underscore-named module*) is a shared parser
  used by 4+ tool modules; sibling `caldav_writeback.py`↔`caldav_sync.py` share 3 privates; `src/`
  freely imports `routes/*` privates. Only **2 of 127** `src/` modules declare `__all__`.
- **Realized cost (verified latent bug):** `src/teacher_escalation.py:236` does
  `from src.ai_interaction import _resolve_model, _TEACHER_SYSTEM_PROMPT`, but `_TEACHER_SYSTEM_PROMPT`
  was moved to `agent_tools/model_interaction_tools.py:20` and no longer exists in `ai_interaction`
  → **ImportError when `_call_teacher` runs.** Exactly the hazard Principle 3 warns about — a
  `_private` treated as a cross-module contract, silently broken by a refactor. *(Flagged as design
  evidence, not a bug-hunt item; worth a real fix.)*
- **Done right:** `src/agent_loop.py` — 43 private funcs, 3 public (`stream_agent_loop`,
  `get_builtin_overrides`, `build_active_plan_note`), **zero** private leakage. The model the rest of
  the repo should copy.

## 4. Duck typing vs. type-checking

Deepest structural issue. **NOTE: refactoring the `agent_loop.py`/`llm_core.py` branching is a
separate, deliberate decision to make later — NOT something to do as a side effect of this audit.**
It works today; this is a flagged POODR violation, not an action item.

- **Provider identity is a `str` tag, re-opened everywhere.** `_detect_provider`
  (`src/llm_core.py:819`) collapses a URL to a string; ~9 downstream sites branch on it — payload
  build (`:2001`, `:2156`), SSE parse (`:2224/:2290/:2352`), `_provider_headers` (`:950`),
  `_provider_label` (`:968`), `_stream_target_url` (`:2092`). Adding a provider = edit ~9 places in
  the right order. **Verified drift already exists:** `_provider_label` labels xAI/DeepSeek/Google/
  Together (`:974/:987/:989/:990`) that `_detect_provider` doesn't recognize — they silently fall
  through to `"openai"`.
- **Model capability by name-substring, spread across ~5 lists.** `_is_api_model` cluster
  `src/agent_loop.py:3034-3078` (`_model_supports_tools`, `_model_no_tools`) plus
  `_THINKING_MODEL_PATTERNS`, `_MAX_COMPLETION_TOKENS_MODELS`, `_FIXED_TEMPERATURE_MODELS` in
  `llm_core.py`. One model's traits live in ~5 hardcoded substring lists across two files. POODR's
  answer: a `Provider`/`ModelProfile` object answering `supports_tools?`, `parse_stream()`, etc.
- **Tool dispatch by name (`src/tool_execution.py:719-926`):** ~40-branch `if tool == "…"` ladder;
  every new tool edits it. The trailing `mcp__` `startswith` branch is the one spot that generalized.
- **Legit, not findings:** most of the 820 `isinstance` uses are `str`-vs-`list` content coercion at
  external-API boundaries (`llm_core.py:1217`, `:952`) — POODR permits this.

## 5. Inheritance vs. composition — a genuine strength

Little to fix. Inheritance is used sparingly and honestly; composition/duck-typing dominates.

- `MemoryProvider(ABC)` `src/memory_provider.py:33` — real abstract contract (4 `@abstractmethod`s);
  `NativeMemoryProvider` is-a provider; `MemoryProviderRegistry:251` uses **composition**
  (holds+delegates) — the exact POODR split.
- `agent_tools` — ~26 tool classes with **no base class**, wired by a dict registry
  (`__init__.py:36`), sharing only a structural `execute()` contract: duck typing over an
  inheritance tree.
- `ChatGPTSubscription*` exceptions (`src/chatgpt_subscription.py:48-61`) — shallow honest is-a for
  catch-granularity.
- **No inheritance hierarchy in `src/` is deeper than 2 levels** — no fragile towers.

## 6. TRUE (on the highest-churn files)

- `agent_loop.py` (4,481 lines, **0 classes**, 94 commits) — **not Transparent/Reasonable**: a
  procedural pipeline around a 1,934-line generator; one tool change ripples to schema-merge +
  resolution + execution + prompt/domain maps.
- `email_routes.py` (5,223 lines, state in a ~4,100-line closure) — **not Reasonable/Usable**: no
  helper is reusable/testable outside the HTTP wiring.
- `llm_core.py` (2,831) — **Reasonable in the small** (clean helpers like `_is_ollama_native_url`,
  `_build_ollama_payload`) but the two streaming entry points re-implement provider dispatch
  independently, so the most common change is the most painful.
- `cookbook_routes.py` (4,386, 0 classes) — vendor/OS branches hard-coded inline in mega-functions;
  a new backend = surgery, not a strategy.

## 7. Law of Demeter

- **Train wrecks — moderate, most-repeated routes smell:** `request.app.state.auth_manager.<method>()`
  (four hops) at `routes/chat_routes.py:936`, with defensive
  `getattr(getattr(request.app,"state",None),"auth_manager",None)` at `chat_helpers.py:136`,
  `document_routes.py:84`. A `get_auth_manager(request)` accessor collapses it to one trusted call.
- **`getattr` chains over domain rows (minor):** `session_tools.py:115`
  (`last_accessed or updated_at or created_at`), `session_search.py:111` (`bind.dialect.name`). A
  `row.best_timestamp()` method would hide the shape. *(The 4-dot chains grep surfaces in
  `url_security.py`/`webhook_manager.py` are IP/CIDR literals — verified NOT Demeter violations.)*

## What's actually done well

- **Service/manager layer is real, cohesive OO:** `MemoryManager`, `RAGManager`, `McpManager`,
  `PersonalDocsManager`, `ToolIndex`, `ToolPolicy`, and small single-purpose stream helpers
  (`_DegenerateStreamGuard`, `_HarmonyStreamRouter`, `_EmailHtmlSanitizer`) are textbook TRUE.
- **`MemoryProvider` ABC + registry** and the **base-class-free `agent_tools` registry** are
  exemplary composition/duck-typing.
- **`agent_loop.py`'s public surface** (43 private, 3 public, no leaks) is the right convention,
  applied rigorously.
- **No deep inheritance anywhere** (≤2 levels) — a real Principle-5 win.
- **`EmbeddingClient`** is a clean DI template already in the tree.

**Honest bottom line:** this is not an OO-modeled codebase on its hot path — it's procedural Python
(agent_loop/chat_routes/cookbook_routes define 0 classes; ~650 module-level defs vs ~59 classes, many
of which are Pydantic/exceptions/dataclasses). That's a legitimate, common choice for a fast-moving
project, and the domain layer shows the team *can* do clean OO. The highest-leverage, lowest-regret
improvements — if/when you choose them — are a `get_db` session dependency (kills the 270-site +
testability problem), reversing the `src/→routes/` imports, and a `Provider` strategy object (kills
the 9-site dispatch + the observed label/detect drift). The mega-function decompositions and the
`_is_api_model` refactor are larger, deliberate projects.

---

# SYNC BLOCK (paste into another AI assistant)

```
POODR DESIGN AUDIT — Odysseus src/ + routes/ (2026-07-19, read-only, verified-not-assumed)
Design-quality only; excludes fix/local-tool-calling changes and HANDOFF.md accepted tradeoffs.

VERDICT: hot path is procedural (agent_loop.py / chat_routes.py / cookbook_routes.py define
0 classes each; ~650 module-level defs vs ~59 classes, many Pydantic/exception/dataclass).
Service/manager layer is genuinely clean OO. Pain is concentrated, not pervasive.

TOP FINDINGS (all verified against code this session):
1. SRP mega-functions (will-cause-pain): stream_agent_loop src/agent_loop.py:2547 (~1,934 lines,
   to EOF); setup_email_routes routes/email_routes.py:1110 (~4,100-line function, 54 route
   handlers + IMAP pool + 5 caches in one closure); _stream_llm_inner src/llm_core.py:2126 (~620);
   chat_stream routes/chat_routes.py:536 (~1,057); _build_system_prompt src/agent_loop.py:1529 (~558).
2. Stringly-typed provider dispatch (Principle 4, biggest structural issue): _detect_provider
   src/llm_core.py:819 returns a str tag re-opened at ~9 sites (payload build 2001/2156, SSE parse
   2224/2290/2352, headers 950, label 968, target_url 2092). CONFIRMED DRIFT: _provider_label labels
   xAI/DeepSeek/Google/Together (974/987/989/990) that _detect_provider doesn't recognize -> silently
   become "openai". Model capability = name-substring guesses spread across ~5 lists (_is_api_model
   agent_loop.py:3034-3078 + _THINKING_MODEL_PATTERNS/_MAX_COMPLETION_TOKENS_MODELS/_FIXED_TEMPERATURE
   in llm_core.py). NOTE: refactoring this is a SEPARATE deliberate decision, not an audit side effect.
3. No DB-session DI: 270 inline SessionLocal(), 0 Depends(get_db) providers -> tools/routes can't be
   tested without monkeypatching. EmbeddingClient src/embeddings.py:45 is the good DI template.
4. Inverted dependency direction: 11 src/ files import from routes/ (e.g. settings.py:291 ->
   routes.prefs_routes; caldav_sync.py:278; service_health.py:315). Stable code depends on volatile
   HTTP layer; inline-import-in-try/except masks the resulting cycles.
5. Leaky private interface (Principle 3): _resolve_model (ai_interaction.py:76) imported at 9 sites/7
   modules; _detect_provider at 5; underscore-named module src/tools/_common.py shared by 4+ modules;
   only 2/127 src modules declare __all__. REALIZED: teacher_escalation.py:236 imports
   _TEACHER_SYSTEM_PROMPT from ai_interaction where it no longer exists (moved to
   agent_tools/model_interaction_tools.py:20) -> LATENT ImportError when _call_teacher runs.
6. Demeter train wrecks: request.app.state.auth_manager.<method>() (4 hops) chat_routes.py:936,
   chat_helpers.py:136, document_routes.py:84 (nested-getattr defensiveness is the symptom).

DONE WELL (don't "fix"): MemoryProvider(ABC)+registry memory_provider.py:33/251 (is-a + composition);
agent_tools base-class-free dict registry __init__.py:36 (duck typing); ChatGPTSubscription exception
tree; agent_loop.py public surface (43 private/3 public, 0 leaks); no inheritance deeper than 2 levels;
clean service classes (MemoryManager/RAGManager/McpManager/ToolIndex/ToolPolicy).

HIGHEST-LEVERAGE, LOWEST-REGRET (each a deliberate choice): (a) get_db session dependency -> migrate
270 SessionLocal() sites; (b) reverse src/->routes/ imports (move shared helpers down); (c) Provider
strategy object -> collapse the 9-site dispatch + kill the label/detect drift; (d) fix the
teacher_escalation ImportError + promote _resolve_model to a public name.

UNVERIFIED / NEEDS INPUT:
- Inline-import total (~1,300) and cross-module underscore-import total (~99) are agent-estimated,
  not exhaustively recounted; the pattern and representative sites ARE verified.
- src->routes count: verified 11 files; an agent said "36 places/13 files" (import-statement vs file
  count) -- treat 11 files as the verified floor.
- Individual line numbers mostly spot-verified; a handful come from sub-agent reads not independently
  re-opened. The high-stakes ones (provider drift, email god-func, teacher ImportError, 270
  SessionLocal, _resolve_model 9 sites) were personally verified.
- The teacher_escalation ImportError is a latent runtime bug found incidentally; this was a design
  audit, not a bug hunt -- confirm before scheduling a fix vs. folding it into the _resolve_model cleanup.
```
