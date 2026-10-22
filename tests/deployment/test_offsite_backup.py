import json
import sys

from scripts.deploy.offsite_backup import upload_snapshot
from trendradar.intelligence.storage import IntelligenceStorage
from trendradar.ops.backup import create_snapshot
from trendradar.ops.health import _latest_backup


def _snapshot(tmp_path):
    database = tmp_path / "intelligence.db"
    with IntelligenceStorage(database):
        pass
    result = create_snapshot([database], tmp_path / "backups", release_id="offsite-test")
    return tmp_path / "backups" / result["backup_id"]


def test_restic_receipt_is_bound_and_secret_free(tmp_path):
    snapshot = _snapshot(tmp_path)
    fake = tmp_path / "fake_restic.py"
    fake.write_text(
        "import json\n"
        "print(json.dumps({'message_type': 'summary', 'snapshot_id': 'remote-123'}))\n",
        encoding="utf-8",
    )
    result = upload_snapshot(
        snapshot,
        restic_bin=[sys.executable, str(fake)],
        repository="s3:https://secret.example/repository",
        password_file=str(tmp_path / "password"),
    )
    receipt = json.loads((snapshot / "offsite-manifest.json").read_text(encoding="utf-8"))
    assert result["success"] is True
    assert receipt["backup_id"] == result["backup_id"]
    assert receipt["manifest_sha256"] == result["manifest_sha256"]
    assert receipt["remote_snapshot_id"] == "remote-123"
    assert "secret.example" not in json.dumps(receipt)
    assert "restic_output" not in receipt


def test_offsite_requires_remote_snapshot_id(tmp_path):
    snapshot = _snapshot(tmp_path)
    fake = tmp_path / "fake_restic.py"
    fake.write_text("print('{}')\n", encoding="utf-8")
    try:
        upload_snapshot(
            snapshot,
            restic_bin=[sys.executable, str(fake)],
            repository="repo",
            password_file="password",
        )
    except ValueError as exc:
        assert "snapshot id" in str(exc)
    else:
        raise AssertionError("missing remote snapshot id was accepted")
    assert not (snapshot / "offsite-manifest.json").exists()


def test_offsite_health_uses_snapshot_age_after_upload(tmp_path):
    snapshot = _snapshot(tmp_path)
    manifest_path = snapshot / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["created_at"] = "2020-01-01T00:00:00+00:00"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    fake = tmp_path / "fake_restic.py"
    fake.write_text(
        "import json\n"
        "print(json.dumps({'message_type': 'summary', 'snapshot_id': 'remote-old'}))\n",
        encoding="utf-8",
    )
    upload_snapshot(
        snapshot,
        restic_bin=[sys.executable, str(fake)],
        repository="repo",
        password_file="password",
    )
    assert _latest_backup(tmp_path / "backups", offsite=True)["data_age_seconds"] > 1_000_000
