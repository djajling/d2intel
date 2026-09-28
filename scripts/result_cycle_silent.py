"""Silent runner for the d2intel 30-minute result cycle (no console window).

Same pattern as live_cycle_silent.py: runs scripts/result_cycle.bat through
cmd.exe with CREATE_NO_WINDOW so no console ever steals foreground focus.
Exit code is propagated from the bat file.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(r"C:\Users\SystemX\ZCodeProject\d2intel")
BAT = ROOT / "scripts" / "result_cycle.bat"

CREATE_NO_WINDOW = 0x08000000


def main() -> int:
    if not BAT.is_file():
        print(f"result_cycle_silent: bat not found: {BAT}", file=sys.stderr)
        return 2

    completed = subprocess.run(
        ["cmd", "/c", str(BAT)],
        cwd=str(ROOT),
        creationflags=CREATE_NO_WINDOW,
    )
    return int(completed.returncode)


if __name__ == "__main__":
    sys.exit(main())
