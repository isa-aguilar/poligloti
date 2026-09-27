"""Copy the demo learner (examples/demo/alex) into DATA_DIR.

Usage: python -m scripts.load_demo
Never overwrites: if the learner already exists, nothing is copied.
"""

from __future__ import annotations

import shutil
import sys

from backend import config

DEMO = config.REPO_ROOT / "examples" / "demo"


def main() -> int:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    for learner in sorted(p for p in DEMO.iterdir() if p.is_dir()):
        target = config.DATA_DIR / learner.name
        if target.exists():
            print(f"{learner.name}: already in {config.DATA_DIR}, left untouched")
            continue
        shutil.copytree(learner, target)
        print(f"{learner.name}: copied to {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
