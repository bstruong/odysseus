#!/usr/bin/env python3
"""
set_ollama_supports_tools.py — re-apply the local-Ollama native tool-calling flag.

Odysseus only sends native function schemas to an endpoint when
``ModelEndpoint.supports_tools`` is true. For a local Ollama server reached over
the OpenAI-compat ``/v1`` path this flag defaults to NULL, which makes
``agent_loop`` treat the endpoint as text-only (``_is_api_model=False``) and send
ZERO tool schemas — so agent tool-calls silently never fire.

This value lives in ``data/app.db`` (a SQLite file), NOT in git, so it is lost if
the data volume is ever reset. This script re-applies it. It is idempotent:
running it twice is a no-op, and it only ever touches the ``supports_tools``
column of matching rows.

Matches endpoints whose ``base_url`` points at a local Ollama server (host:port
11434) unless ``--base-url`` narrows it further. Writes a ``.bak`` copy of the DB
first.

Usage:
    python3 scripts/set_ollama_supports_tools.py                 # data/app.db
    python3 scripts/set_ollama_supports_tools.py --db /path/app.db
    python3 scripts/set_ollama_supports_tools.py --base-url http://host.docker.internal:11434/v1
    python3 scripts/set_ollama_supports_tools.py --dry-run

Run this AFTER the endpoint has been registered in the UI — if no Ollama endpoint
row exists yet, the script reports that and changes nothing.
"""
import argparse
import os
import shutil
import sqlite3
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DEFAULT_DB = os.path.join(REPO_ROOT, "data", "app.db")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=DEFAULT_DB, help="Path to app.db (default: repo data/app.db)")
    ap.add_argument("--base-url", default=None,
                    help="Only update the endpoint with this exact base_url "
                         "(default: any endpoint whose base_url contains ':11434')")
    ap.add_argument("--dry-run", action="store_true", help="Report what would change, write nothing")
    args = ap.parse_args()

    if not os.path.exists(args.db):
        print(f"ERROR: database not found: {args.db}", file=sys.stderr)
        return 2

    con = sqlite3.connect(args.db)
    con.row_factory = sqlite3.Row
    try:
        if args.base_url:
            rows = con.execute(
                "SELECT id, base_url, supports_tools FROM model_endpoints WHERE base_url = ?",
                (args.base_url,),
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT id, base_url, supports_tools FROM model_endpoints WHERE base_url LIKE ?",
                ("%:11434%",),
            ).fetchall()

        if not rows:
            where = f"base_url = {args.base_url!r}" if args.base_url else "a local Ollama (:11434) base_url"
            print(f"No endpoint found with {where}. Register the endpoint first, then re-run.")
            return 1

        needing = [r for r in rows if r["supports_tools"] != 1]
        for r in rows:
            state = "already set" if r["supports_tools"] == 1 else "WILL SET" if not args.dry_run else "would set"
            print(f"  {r['id']}  {r['base_url']}  supports_tools={r['supports_tools']} -> {state}")

        if not needing:
            print("Nothing to do — all matching endpoints already have supports_tools=1.")
            return 0

        if args.dry_run:
            print(f"[dry-run] {len(needing)} endpoint(s) would be updated.")
            return 0

        bak = args.db + ".bak-supports_tools"
        shutil.copy2(args.db, bak)
        con.execute(
            "UPDATE model_endpoints SET supports_tools = 1 "
            "WHERE supports_tools IS NOT 1 AND id IN (%s)"
            % ",".join("?" * len(needing)),
            [r["id"] for r in needing],
        )
        con.commit()
        print(f"Updated {len(needing)} endpoint(s) to supports_tools=1. Backup: {bak}")
        print("Restart the odysseus container for the change to be read on the next turn.")
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    raise SystemExit(main())
