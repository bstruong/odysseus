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

## Operational notes

- **Web search is per-turn opt-in.** Enable the composer web toggle (visibly active)
  or use `/search <query>`. An unchecked toggle in agent mode sends an explicit deny.
- **VRAM budget** (RTX 3060 12GB): keep model + KV context under ~10,500 MiB total
  (desktop baseline ~800–900 MiB) to avoid Wayland compositor stutter.
