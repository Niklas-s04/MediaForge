"""Container entrypoint: discard only this container's private scratch on restart."""
import os
from pathlib import Path
import shutil
import sys


def reset_scratch(root: Path) -> None:
    if root.is_symlink():
        raise RuntimeError("Scratch root must not be a symlink")
    for name in ("tmp", "jobs"):
        directory = root / name
        if directory.is_symlink():
            raise RuntimeError("Scratch directory must not be a symlink")
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        for entry in directory.iterdir():
            if entry.is_dir() and not entry.is_symlink():
                shutil.rmtree(entry)
            else:
                entry.unlink()


if __name__ == "__main__":
    reset_scratch(Path("/scratch"))
    if len(sys.argv) < 2:
        raise SystemExit("Missing application command")
    os.execvp(sys.argv[1], sys.argv[1:])
