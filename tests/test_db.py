import pytest

from shared.db import JobStore


@pytest.fixture()
def store(tmp_path):
    return JobStore(tmp_path / "vs.db")


def test_create_and_get_roundtrip(store):
    store.create("j1", "https://youtu.be/x", extract_transcript=True, summarize=False)
    row = store.get("j1")
    assert row is not None
    assert row["url"] == "https://youtu.be/x"
    assert row["status"] == "queued"
    assert row["extra"] == '{"extract_transcript": true, "summarize": false}'


def test_get_missing_returns_none(store):
    assert store.get("does-not-exist") is None


def test_update_sets_fields(store):
    store.create("j1", "https://youtu.be/x")
    updated = store.update("j1", status="running", stage="downloading", progress=0.5)
    assert updated["status"] == "running"
    assert updated["stage"] == "downloading"
    assert updated["progress"] == 0.5


def test_update_extra_merges_instead_of_clobbering(store):
    """Regression test: update_extra must not destroy extract_transcript/summarize
    when the pipeline later records media_path. See ingest/main.py's download step."""
    store.create("j1", "https://youtu.be/x", extract_transcript=False, summarize=True)

    store.update_extra("j1", media_path="/data/jobs/j1/media/x.mp4")

    row = store.get("j1")
    import json
    extra = json.loads(row["extra"])
    assert extra["extract_transcript"] is False
    assert extra["summarize"] is True
    assert extra["media_path"] == "/data/jobs/j1/media/x.mp4"


def test_update_extra_survives_special_characters_in_value(store):
    """The old f-string-built extra column broke on quotes/backslashes in paths."""
    store.create("j1", "https://youtu.be/x")
    tricky_path = 'C:\\videos\\weird "name".mp4'

    store.update_extra("j1", media_path=tricky_path)

    row = store.get("j1")
    import json
    extra = json.loads(row["extra"])
    assert extra["media_path"] == tricky_path


def test_update_extra_missing_job_returns_none(store):
    assert store.update_extra("nope", media_path="/x") is None


def test_transcript_roundtrip(store):
    store.create("j1", "https://youtu.be/x")
    segments = [{"start": 0.0, "end": 1.0, "text": "hi"}]
    store.save_transcript("j1", "en", "faster_whisper", "hi", segments)

    transcript = store.get_transcript("j1")
    assert transcript["language"] == "en"
    assert transcript["segments"] == segments


def test_summary_roundtrip(store):
    store.create("j1", "https://youtu.be/x")
    store.save_summary("j1", "eli5 text", "detailed text", ["point one", "point two"])

    summary = store.get_summary("j1")
    assert summary["eli5"] == "eli5 text"
    assert summary["key_points"] == ["point one", "point two"]


def test_downloads_roundtrip(store):
    store.create("j1", "https://youtu.be/x")
    store.save_download("j1", "merged", "/data/jobs/j1/media/x.mp4", 12345)

    downloads = store.get_downloads("j1")
    assert len(downloads) == 1
    assert downloads[0]["type"] == "merged"
    assert downloads[0]["size"] == 12345


def test_delete_removes_job_and_dependents(store):
    store.create("j1", "https://youtu.be/x")
    store.save_transcript("j1", "en", "faster_whisper", "hi", [])
    store.save_summary("j1", "a", "b", [])
    store.save_download("j1", "merged", "/x.mp4", 1)

    store.delete("j1")

    assert store.get("j1") is None
    assert store.get_transcript("j1") is None
    assert store.get_summary("j1") is None
    assert store.get_downloads("j1") == []


def test_list_returns_all_created_jobs(store):
    store.create("j1", "https://youtu.be/1")
    store.create("j2", "https://youtu.be/2")

    ids = {row["id"] for row in store.list()}
    assert ids == {"j1", "j2"}
