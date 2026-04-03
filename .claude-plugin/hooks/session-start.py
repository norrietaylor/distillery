#!/usr/bin/env python3
"""SessionStart hook — surfaces pending review queue at the start of each session.

Run via Claude Code SessionStart hook in .claude/settings.json:
  "command": "python3 .claude-plugin/hooks/session-start.py"

Exits silently (code 0) when distillery is unavailable or the queue is empty.
Prints a one-line reminder when pending_review entries exist.
"""

import json
import subprocess
import sys


def main() -> None:
    try:
        result = subprocess.run(
            ["distillery", "status", "--format", "json"],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        sys.exit(0)
    if result.returncode != 0:
        sys.exit(0)

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        sys.exit(0)

    pending = data.get("entries_by_status", {}).get("pending_review", 0)
    if pending > 0:
        noun = "entry" if pending == 1 else "entries"
        print(f"[Distillery] {pending} {noun} pending review — run /classify to process them.")


if __name__ == "__main__":
    main()
