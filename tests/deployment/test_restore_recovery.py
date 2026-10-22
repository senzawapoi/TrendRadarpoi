import json
from pathlib import Path

import pytest

from trendradar.intelligence.storage import IntelligenceStorage
from trendradar.ops.backup import (
    activate_restore,
    create_snapshot,
    pending_restore_transactions,
)
from trendradar.ops.maintenance import control_directory, main, read_guard


def test_incomplete_restore_transaction_is_visible_and_blocks_retry(tmp_path):
    database = tmp_path / "output" / "intelligence.db"
    database.parent.mkdir()
    with IntelligenceStorage(database):
        pass
    control = control_directory(database)
    control.mkdir(parents=True)
    transaction = control / "restore-activation-interrupted.json"
    transaction.write_text(
        json.dumps(
            {
                "state": "installing",
                "database": str(database),
                "destinations": [str(database)],
                "installed": [],
            }
        ),
        encoding="utf-8",
    )
    pending = pending_restore_transactions(database)
    assert len(pending) == 1
    assert pending[0]["state"] == "installing"
    with pytest.raises(RuntimeError, match="incomplete transaction"):
        activate_restore(tmp_path / "restored", database)


def test_restore_journal_contains_per_database_operations_and_pre_restore_mapping(tmp_path):
    output = tmp_path / "output"
    output.mkdir()
    intelligence = output / "intelligence.db"
    with IntelligenceStorage(intelligence):
        pass
    snapshot = create_snapshot([intelligence], tmp_path / "backups", root=output)
    restored_path = tmp_path / "restored"
    from trendradar.ops.backup import restore_snapshot

    restore_snapshot(
        tmp_path / "backups" / snapshot["backup_id"],
        restored_path,
        guard_database=intelligence,
    )
    result = activate_restore(restored_path, intelligence, root=output)

    journal = json.loads((control_directory(intelligence) / Path(result["transaction"]).name).read_text())
    assert journal["current_operation"] is None
    assert journal["operations"][0]["installed"] is True
    pre_restore = json.loads(
        (Path(result["previous_snapshot"]["path"]) / "manifest.json").read_text()
    )
    assert pre_restore["databases"][0]["relative_path"] == "intelligence.db"
    assert pre_restore["target_mapping"] == [
        {"relative_path": "intelligence.db", "present": True}
    ]
    assert journal["state"] == "complete"
    assert pending_restore_transactions(intelligence) == []
    assert read_guard(intelligence) is not None
    assert main(["clear", "--database", str(intelligence)]) == 0
    assert read_guard(intelligence) is None
