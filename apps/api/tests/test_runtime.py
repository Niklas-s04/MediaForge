import importlib
import pytest


def test_api_does_not_create_worker_scratch(tmp_path, monkeypatch):
    runtime = importlib.import_module("apps.api.app.runtime")
    monkeypatch.delenv("DATA_TMP_DIR", raising=False)
    root = tmp_path / "scratch"
    monkeypatch.setenv("TMPDIR", str(root / "tmp"))
    runtime.prepare_scratch(root, tmp_path / "fallback")
    assert (root / "tmp").is_dir()
    assert not (root / "jobs").exists()


def test_read_only_scratch_uses_private_writable_fallback(tmp_path, monkeypatch):
    import errno
    from pathlib import Path
    runtime = importlib.import_module("apps.api.app.runtime")
    root = tmp_path / "scratch"
    fallback = tmp_path / "fallback"
    monkeypatch.setenv("TMPDIR", str(root / "tmp"))
    monkeypatch.setenv("DATA_TMP_DIR", str(root / "jobs"))
    original = Path.mkdir
    def read_only(path, *args, **kwargs):
        if path == root or root in path.parents:
            raise OSError(errno.EROFS, "Read-only file system", str(path))
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "mkdir", read_only)
    runtime.prepare_scratch(root, fallback)
    assert runtime.os.environ["TMPDIR"] == str(fallback / "tmp")
    assert runtime.os.environ["DATA_TMP_DIR"] == str(fallback / "jobs")
    assert (fallback / "jobs").is_dir()


@pytest.mark.parametrize("expect_fallback", [True, False])
def test_existing_scratch_is_checked_for_writability(tmp_path, monkeypatch, expect_fallback):
    import errno
    runtime = importlib.import_module("apps.api.app.runtime")
    root, fallback = tmp_path / "scratch", tmp_path / "fallback"
    (root / "tmp").mkdir(parents=True)
    monkeypatch.delenv("DATA_TMP_DIR", raising=False)
    monkeypatch.setenv("TMPDIR", str(root / "tmp"))
    original = runtime.tempfile.TemporaryFile
    def probe(*args, **kwargs):
        if kwargs.get("dir") == root / "tmp":
            raise OSError(errno.EROFS if expect_fallback else errno.ENOSPC, "write failed")
        return original(*args, **kwargs)
    monkeypatch.setattr(runtime.tempfile, "TemporaryFile", probe)
    if expect_fallback:
        runtime.prepare_scratch(root, fallback)
        assert runtime.os.environ["TMPDIR"] == str(fallback / "tmp")
    else:
        with pytest.raises(OSError) as failure:
            runtime.prepare_scratch(root, fallback)
        assert failure.value.errno == errno.ENOSPC
        assert not fallback.exists()


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
