import json
from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlmodel import Session, SQLModel, create_engine, select

from apps.api.app import main
from apps.api.app.compression import normalize_compression
from apps.api.app.models import Job


@pytest.mark.parametrize("filename,settings", [
    ("image.jpg", {"output_format": "mp4"}),
    ("file.bin", {"output_format": "pdf"}),
    ("image.gif", {"output_format": "webp"}),
    ("movie.mp4", {"crf": 99}),
    ("song.wav", {"audio_bitrate": "-y"}),
    ("text.txt", {"level": 0}),
    ("doc.pdf", {"pdf_dpi": "72.5"}),
])
def test_reject_invalid_compression_options(filename, settings):
    with pytest.raises(ValueError):
        normalize_compression(filename, settings)


def test_compression_batch_scans_dispatches_and_preserves_individual_options(monkeypatch, tmp_path):
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    scanned, dispatched = [], []
    monkeypatch.setenv("DATA_UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(main, "scan_file", lambda path: scanned.append(path))
    monkeypatch.setattr(main, "dispatch_job", lambda job: dispatched.append(job.id))
    files = [SimpleNamespace(filename=name, content_type="application/octet-stream", file=BytesIO(b"test"))
             for name in ["a.mp4", "b.xyz", "c.xlsx"]]
    with Session(engine) as session:
        result = main.create_convert_batch_jobs(files=files, operation="compress", settings=json.dumps([
            {"output_format": "webm", "crf": "28"}, {"output_format": "xz", "level": 9}, {"output_format": "xlsx"},
        ]), session=session)
        jobs = session.exec(select(Job).order_by(Job.id)).all()
        assert len(result["jobs"]) == len(scanned) == len(dispatched) == 3
        assert all(job.type == "compress" for job in jobs)
        assert jobs[0].input["crf"] == 28
        assert jobs[1].input["level"] == 9
        assert jobs[2].input["output_format"] == "xlsx"


def test_invalid_batch_stores_nothing(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_UPLOAD_DIR", str(tmp_path))
    files = [SimpleNamespace(filename="a.txt", content_type="text/plain", file=BytesIO(b"data"))]
    with pytest.raises(HTTPException) as error:
        main.create_convert_batch_jobs(files=files, operation="compress", settings='[{"output_format":"mp4"}]', session=None)
    assert error.value.status_code == 400
    assert not list(tmp_path.iterdir())
