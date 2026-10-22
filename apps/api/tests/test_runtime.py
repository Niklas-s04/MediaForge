import importlib
import pytest


def test_private_scratch_is_cleared_without_touching_siblings(tmp_path):
    # A restart must remove stale conversion/spool files, never persisted data.
    scratch = tmp_path / "scratch"
    (scratch / "tmp" / "old-work").mkdir(parents=True)
    (scratch / "tmp" / "old-work" / "partial").write_bytes(b"stale")
    (scratch / "jobs").mkdir()
    (scratch / "jobs" / "job-1").write_bytes(b"stale")
    kept = tmp_path / "uploads"
    kept.mkdir()
    (kept / "input").write_bytes(b"keep")
    runtime = importlib.import_module("apps.api.app.runtime")
    runtime.reset_scratch(scratch)
    assert list((scratch / "tmp").iterdir()) == []
    assert list((scratch / "jobs").iterdir()) == []
    assert (kept / "input").read_bytes() == b"keep"


def test_scratch_symlink_is_not_followed(tmp_path):
    protected = tmp_path / "protected"
    protected.mkdir()
    (protected / "keep").write_bytes(b"keep")
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    try:
        (scratch / "tmp").symlink_to(protected, target_is_directory=True)
    except OSError:
        pytest.skip("Symlinks require privileges on this Windows host")
    runtime = importlib.import_module("apps.api.app.runtime")
    with pytest.raises(RuntimeError):
        runtime.reset_scratch(scratch)
    assert (protected / "keep").read_bytes() == b"keep"
