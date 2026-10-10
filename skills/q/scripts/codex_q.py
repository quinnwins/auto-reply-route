"""Run the Codex /q helper from the linked skill checkout."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))
from auto_reply_route.codex_batch import main

if __name__ == "__main__":
    sys.exit(main())
