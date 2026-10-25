# Odysseus — Agent & Scoped Execution Conventions

Self-hosted AI workspace for chat, agents, research, documents, email, notes, and calendar.

## Scoped Execution Rules for Local MoE Agents (CRITICAL)
This repository is a large monorepo (`app.py` > 60 KB, dozens of routes/services, and a large test suite). To avoid exhausting context window or prefill budgets on local GPU hardware:
1. **Never scan the entire repository or read all of `app.py` at once.** Use targeted `grep` / line-range reads on the specific module under `core/`, `routes/`, `services/`, or `src/`.
2. **Always run targeted single-file or focused tests** rather than the full test suite:
   - Single test file: `pytest tests/test_<module>.py -q`
   - Fast-lane focus runner: `python3 tests/run_focus.py <keyword>` (excludes `@pytest.mark.slow`)
3. **Secret & Privacy Gate:** Run `gitleaks detect --source .` if touching configuration or auth files. Keep `AUTH_ENABLED=true` and `LOCALHOST_BYPASS=false` outside local dev.
