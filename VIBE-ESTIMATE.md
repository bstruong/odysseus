# VIBE-ESTIMATE.md — proxy-signal estimate of low-review / rushed code

**Purpose:** an evidence-based *estimate* of how much low-review / AI-assisted-and-barely-checked /
rushed code is in Odysseus. **There is NO reliable way to detect "AI-written" vs "human-written" code**
— everything below is an observable *proxy*, with explicit confidence. Same standard as the churn and
audit reports: real data, honest uncertainty, no invented precision. Scope: `src/` + `routes/`,
analyzed on `origin/dev` (the fuller branch). Read-only. **No contributor is named** — patterns and
time windows only. Verified this session (2026-07-19).

Tools used: pyflakes 3.4.0 + vulture 2.16 (installed into an isolated scratchpad venv — no system/repo
change), git log/shortlog, AST/regex counters.

---

## OVERALL ESTIMATE (speculative — clearly labeled)

The signals are **mixed and mostly point to fast-moving OSS with a rushed *initial* dump that was
subsequently cleaned up — NOT a pervasively vibe-coded, barely-checked codebase.**

Rough figure, low confidence: **~15–30% of the current code carries elevated "rushed/low-review"
proxy signals**, concentrated in (a) the initial late-May scaffolding and (b) the largest procedural
modules. The majority shows normal review/test/iteration hygiene. **Low confidence in the exact %;
higher confidence in the "concentrated, not pervasive" shape.**

---

## STRONGEST EVIDENCE (with confidence)

**1. Test ratio shows a "rushed start, then cleanup" curve — CONFIDENCE: HIGH (git-derived).**
Lines added per month, tests/ vs src+routes/:
- 2026-05: tests +2,674 | code +60,208 → ratio **0.04** (initial dump was almost untested)
- 2026-06: tests +77,647 | code +52,755 → ratio **1.47** (tests OUTPACED code)
- 2026-07: tests +8,405 | code +10,145 → ratio **0.83**
723 test files exist now (vs 192 source files; test LOC 59,826 ≈ 0.38× the 157,230 source LOC). So the
low-review signal is real but **localized to the May origin**; the project then back-filled tests
heavily. Single most informative finding.

**2. `email_routes.py` looks bulk-dropped; `agent_loop.py`/`llm_core.py` look iterated — CONFIDENCE: MODERATE.**
Per-commit line additions (origin/dev):
- `email_routes.py`: **3,038 then 1,281 lines in two commits** (~75% of its 5,223 lines), 43 commits total → generate-and-drop pattern.
- `agent_loop.py`: 95 commits, largest single add 2,106 then mostly <300 → incremental human iteration.
- `llm_core.py`: 67 commits, largest 913 then <250 → incremental.
The "vibe" signal is **module-specific, not uniform**; the biggest god-function (email_routes) is the strongest bulk-drop candidate.

**3. A real PR/review workflow exists, and commit messages read human — CONFIDENCE: MODERATE-HIGH.**
Of 1,937 commits: **53% carry a `(#PR)` reference** (merge-via-PR), 46% conventional-commit prefix,
3% merges, median subject length 59 chars. Top first-words after the colon are human imperatives —
*nudge, keep, stop, don't, prevent, drop* — not templated "Add feature X." 81 code comments cite issue
numbers (`#1567`, `#2927`) with real context. Argues **against** wholesale unreviewed AI dumping.
*Caveat: PR-linkage proves a process exists, not that review was rigorous.*

**4. A few concrete latent bugs from unreviewed paths — CONFIDENCE: HIGH (verified).**
pyflakes/vulture found real, linter-catchable errors sitting in live code:
- `src/caldav_writeback.py:77` & `:79` use `datetime.strptime(...)` but the file only does
  `from datetime import timezone` (line 21) → **NameError** when that exdate path runs (verified — not
  an inline-import false positive).
- `routes/cookbook_routes.py:3688` — undefined name `repo`.
- `src/teacher_escalation.py:236` — imports `_TEACHER_SYSTEM_PROMPT` from `ai_interaction` where it no
  longer exists (moved to `agent_tools/model_interaction_tools.py:20`) → **ImportError** (from AUDIT.md).
**But 3 across 157k lines is LOW density** — the "barely-checked" evidence is sparse, not rampant.

---

## SECONDARY SIGNALS

- **Dead code (tool-derived): moderate cruft, little truly-dead code.** pyflakes: 265 findings — 235
  imported-but-unused, 24 redefinition/unused, 3 real undefined names, 1 star-import. vulture ≥80%
  confidence: only **16** (12 unused import, 3 unused variable). Few dead functions/classes → not heavy
  AI-scaffold dumping. CONFIDENCE: HIGH (objective).
- **Defensive/swallow patterns: elevated.** 1,367 broad `except Exception`, **0** bare `except:`, **272**
  `except …: pass` (silent swallow), 2,043 `try:` blocks over 157,230 non-blank lines. Elevated
  "make-it-work" defensiveness, but partly justified by the I/O-heavy domain (DB/IMAP/HTTP/LLM stream).
  CONFIDENCE: MODERATE.
- **Comment density normal, quality human.** 8.7% comment lines (7,345 / 76,896 code) — not
  "unusually verbose textbook comments." 81 issue-referencing comments; the core files' comments explain
  *why* with real context. 1,826 docstring blocks (NOT sampled for templating — see limits). CONFIDENCE:
  MODERATE.
- **Duplication: some, not rampant (copy-paste proxy).** Duplicate function names across files are low
  (`execute` 26× is the intentional duck-typed tool contract, `__init__` 31× normal; others 4–5×). The
  real duplication is the provider dispatch ladders in `llm_core.py` (AUDIT.md #4), not scattered
  regenerated helpers. CONFIDENCE: LOW-MODERATE.

---

## WHAT THIS CANNOT TELL US (limits — read before acting)

- **It cannot distinguish AI-generated from human-written code.** All proxies, no proof.
- **Fast solo/OSS human development produces the same signals** — big commits, procedural mega-functions,
  defensive `except`, an untested initial dump. Genuinely cannot separate "AI-assisted-and-reviewed"
  from "human, rushed."
- **53% PR-linkage = a process, not review *quality*** — rubber-stamp merges look identical.
- **723 test files = test *volume*, not *coverage/quality*** — no assertion count / coverage run; the
  surviving `datetime` NameError shows some paths are untested.
- **No contributor attribution** — did not cluster by author (and would not name anyone); reliable
  voice-clustering across 330 contributors isn't feasible here.
- **The May "dump" could be an import of pre-existing code**, not fresh generation.
- **1,826 docstrings were NOT rigorously sampled** for templated/AI-boilerplate patterns — signal
  unassessed.
- Analysis is `origin/dev` only; `main` lags dev by 44 commits (see churn report).

---

## DOES THIS CHANGE THE POODR AUDIT?

**No — it explains it, doesn't overturn it.** The procedural hot path and mega-functions correlate
cleanly with the rushed-initial-dump + bulk-drop pattern (e.g. `email_routes.py` as a 4,100-line
god-function added in two commits). "Vibe-y origins" is a plausible *why* for the structure the audit
found, but the remediation (decompose mega-functions, add DB-session DI, break the provider dispatch)
is identical regardless of authorship. **One practical add-on:** the sparse latent name/import bugs
(`datetime`, `repo`, `_TEACHER_SYSTEM_PROMPT`) suggest **adding pyflakes to CI** would cheaply catch
this exact class of unreviewed-path bug going forward.

---

## SYNC BLOCK (paste into another AI assistant)

```
VIBE-CODING PROXY ESTIMATE — Odysseus src/+routes/ (2026-07-19, origin/dev, verified, proxies-not-proof)
NO reliable AI-vs-human detection exists; below are observable proxies w/ confidence. No contributors named.
Tools: pyflakes 3.4.0 + vulture 2.16 (isolated venv), git log, AST counters.

ESTIMATE (speculative): signals are MIXED -> fast-moving OSS with a rushed INITIAL dump later cleaned up,
NOT pervasively vibe-coded. Rough ~15-30% of code carries elevated rushed/low-review signals, CONCENTRATED
in (a) the late-May scaffold and (b) the biggest procedural modules. Low confidence on %; higher on "shape".

STRONGEST EVIDENCE:
1. Test ratio curve (HIGH): tests/code added per month = May 0.04 (60k code, ~zero tests) -> Jun 1.47
   (tests outpaced code) -> Jul 0.83. 723 test files now. Low-review signal is LOCALIZED to May origin;
   tests were heavily back-filled after.
2. Bulk-drop vs iteration (MODERATE): email_routes.py = 3038+1281 lines in 2 commits (~75% of 5223 LOC,
   43 commits total) -> generate-and-drop. agent_loop.py (95 commits, then <300/commit) & llm_core.py
   (67 commits) grew incrementally -> human iteration. Signal is module-specific.
3. Real review process + human messages (MOD-HIGH): 53% of 1937 commits have (#PR); human imperative
   commit voice (nudge/keep/stop/don't/prevent), 81 issue-ref comments. Argues AGAINST wholesale AI dump.
   (PR-linkage = process exists, not review quality.)
4. Sparse latent bugs from unreviewed paths (HIGH, verified): caldav_writeback.py:77/79 use datetime.strptime
   but only `from datetime import timezone` imported -> NameError; cookbook_routes.py:3688 undefined `repo`;
   teacher_escalation.py:236 ImportError. Only 3 across 157k lines -> LOW density, not rampant.

SECONDARY: pyflakes 235 unused imports (moderate) but vulture only 16 high-conf dead items (little dead
code); 272 silent `except: pass` + 1367 broad `except Exception` (elevated defensiveness, partly justified);
comment density 8.7% (normal), human WHY-comments; duplication = provider ladders (AUDIT.md), not rampant
copy-paste.

CANNOT TELL: AI-vs-human (no proof); fast human OSS looks identical; PR% != review quality; 723 test files
= volume not coverage; no author attribution; May dump could be imported code; docstrings not sampled.

EFFECT ON AUDIT: explains WHY the hot path is procedural; does NOT change remediation. ADD-ON: put pyflakes
in CI to catch the undefined-name/unused-import class cheaply.
```
