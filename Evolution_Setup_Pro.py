"""Legacy launcher for Evolution System v7.7.7 Absoluta."""

import runpy
from pathlib import Path


if __name__ == "__main__":
    runpy.run_path(
        str(Path(__file__).with_name("Evolution System v7.7.7 Absoluta.py")),
        run_name="__main__",
    )
