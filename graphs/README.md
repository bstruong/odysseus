# graphs/ — module dependency graphs

AST-derived dependency graphs of `src/` + `routes/` (192 modules, 605 edges), computed
2026-07-19. Four views:

- `deps_modules.dot` — full file-to-file graph (dense; filter/search)
- `deps_hotpath.dot` — `agent_loop`/`chat_routes`/`llm_core` + 1-hop neighbors
- `deps_service.dot` — clean service layer + neighbors, module level
- `deps_service_classes.dot` — `MemoryProvider` ABC is-a + instantiation sites

Key findings from this analysis are written up in `AUDIT.md` (one ~50-module strongly-connected
component spanning the hot path + tools + ~14 route modules; 22 `src`→`routes` back-edges from
13 files; `tool_policy` pulled into the SCC via a mutual import with `agent_loop`).

## Regenerating the rendered SVGs (trivial — do this, don't commit SVGs)

The `.dot` files are the committed source; SVGs are git-ignored and rendered on demand:

```
dot -Tsvg graphs/deps_modules.dot         -o graphs/deps_modules.svg
dot -Tsvg graphs/deps_hotpath.dot         -o graphs/deps_hotpath.svg
dot -Tsvg graphs/deps_service.dot         -o graphs/deps_service.svg
dot -Tsvg graphs/deps_service_classes.dot -o graphs/deps_service_classes.svg
```

Requires graphviz's `dot` CLI (rendered originally with graphviz 15.1.0). PNGs, if wanted:
`dot -Tpng -Gdpi=120 graphs/<view>.dot -o graphs/<view>.png`.

## Regenerating the `.dot` files themselves — NOT currently possible

The `.dot` files were produced by a one-off "stdlib `ast` extractor + Tarjan SCC" script
(per the commit that added them). **That extractor script was never committed to this repo**
— it isn't in git history (checked `git log --all --diff-filter=A` for anything AST/graph-related)
and isn't present untracked on disk either. The `.dot` files themselves are therefore the only
surviving artifact of that analysis; if they're ever lost, reproducing them requires writing a
new AST-extraction script from scratch, not just re-running an existing one. Kept as small,
human-readable, diffable text for this reason — do not delete without archiving elsewhere first.
