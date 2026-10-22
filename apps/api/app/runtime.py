"""Container entrypoint: discard only this container's private scratch on restart."""
import os
import errno
from pathlib import Path
import shutil
import sys
import tempfile


def reset_scratch(root: Path, names=("tmp", "jobs")) -> None:
    if root.is_symlink():
        raise RuntimeError("Scratch root must not be a symlink")
    for name in names:
        directory = root / name
        if directory.is_symlink():
            raise RuntimeError("Scratch directory must not be a symlink")
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        for entry in directory.iterdir():
            if entry.is_dir() and not entry.is_symlink():
                shutil.rmtree(entry)
            else:
                entry.unlink()


def prepare_scratch(root: Path = Path("/scratch"), fallback: Path = Path("/tmp/mediaforge-scratch")) -> None:
    # The API has no conversion directory. Older NAS definitions may mount only
    # /tmp, so an image update must not require a writable container root.
    uses_jobs = os.environ.get("DATA_TMP_DIR") == str(root / "jobs")
    names = ("tmp", "jobs") if uses_jobs else ("tmp",)
    selected = root
    try:
        reset_scratch(root, names)
        for name in names:
            with tempfile.TemporaryFile(dir=root / name):
                pass
    except OSError as exc:
        if exc.errno not in (errno.EROFS, errno.EACCES):
            raise
        selected = fallback
        reset_scratch(selected, names)
        for name in names:
            with tempfile.TemporaryFile(dir=selected / name):
                pass
        print(f"WARNING: {root} is not writable; using {selected}. "
              "Mount a private writable volume at /scratch for disk-backed temporary files.",
              file=sys.stderr, flush=True)
    if os.environ.get("TMPDIR", str(root / "tmp")) == str(root / "tmp"):
        os.environ["TMPDIR"] = str(selected / "tmp")
        tempfile.tempdir = None
    if uses_jobs:
        os.environ["DATA_TMP_DIR"] = str(selected / "jobs")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("Missing application command")
    prepare_scratch()
    os.execvp(sys.argv[1], sys.argv[1:])
