"""Silent runner for the d2intel 5-minute live cycle (no console window).

Runs scripts/live_cycle.bat through cmd.exe with CREATE_NO_WINDOW so no
console is ever created — a visible window would steal foreground focus from
Dota 2 (fullscreen) and kick the game to a black screen every 5 minutes.

Exit code is propagated from the bat file.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(r"C:\Users\SystemX\ZCodeProject\d2intel")
BAT = ROOT / "scripts" / "live_cycle.bat"

CREATE_NO_WINDOW = 0x08000000


def main() -> int:
    if not BAT.is_file():
        print(f"live_cycle_silent: bat not found: {BAT}", file=sys.stderr)
        return 2

    completed = subprocess.run(
        ["cmd", "/c", str(BAT)],
        cwd=str(ROOT),
        creationflags=CREATE_NO_WINDOW,
    )
    return int(completed.returncode)


if __name__ == "__main__":
    sys.exit(main())
