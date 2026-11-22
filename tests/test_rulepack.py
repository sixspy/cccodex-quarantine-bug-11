import threading

import pytest

from app.db import get_db
from app.services import captures, policies, quarantine, review, rulepack
from app.services.errors import ServiceError


def _first_bad_item(db_path):
    batch = next(b for b in captures.list_batches(db_path) if b["status"] != "已关闭")
    detail = captures.get_batch(batch["id"], db_path)
    item = next(
        i for i in detail["items"] if i["quality"] != "合格" and i["status"] == "待检"
    )
    item["batch_id"] = batch["id"]
    open_bin = next(b for b in quarantine.list_bins(db_path) if b["status"] == "开放")
    return item, open_bin


def test_genesis_pinned_and_aligned(db_path):
    st = rulepack.status(db_path)
    assert st["aligned"] is True
    assert st["badge"] == "规则包已钉"
    assert st["pack_key"] == "RP-CLEAN"
    assert st["pack_version"] == 1
    assert st["read_track"] == "cutover_book"
    assert st["landing"].startswith("切流账册#")
    assert st["rules_fp"] == st["live_fp"]


def test_upgrade_bumps_version_and_moves_pin(db_path):
    st = rulepack.upgrade("RP-CLEAN", "例行升版", "仓管甲", expect_version=1, db_path=db_path)
    assert st["pack_version"] == 2
    assert st["aligned"] is True
    rows = rulepack.status(db_path)["ledger"]
    assert len(rows) == 2
    newest = rows[0]
    assert newest["pack_version"] == 2
    assert newest["active"] is True
    assert rows[1]["active"] is False


def test_fp_drift_blocks_cleaning_until_upgrade(db_path):
    policies.create_rule("新增观察规则", "重复键", "观察", "", "", db_path)
    st = rulepack.status(db_path)
    assert st["aligned"] is False
    assert st["badge"] == "规则包指纹不符"
    item, open_bin = _first_bad_item(db_path)
    with pytest.raises(ServiceError) as exc:
        quarantine.enter_item(item["id"], open_bin["id"], "指纹漂移试入舱", db_path)
    assert exc.value.status_code == 409
    assert "指纹" in exc.value.message
    with pytest.raises(ServiceError):
        policies.apply_to_batch(item["batch_id"], db_path)
    st2 = rulepack.upgrade("RP-CLEAN", "钉死新口径", db_path=db_path)
    assert st2["aligned"] is True
    row = quarantine.enter_item(item["id"], open_bin["id"], "升版后入舱", db_path)
    assert row["status"] == "待复核"


def test_release_blocked_on_fp_drift(db_path):
    policies.create_rule("再漂移", "合格", "观察", "", "", db_path)
    ticket = next(t for t in review.list_tickets(db_path) if t["decision"] == "待决")
    with pytest.raises(ServiceError) as exc:
        review.decide(ticket["id"], "放行", "tester", "", db_path)
    assert exc.value.status_code == 409
    assert "指纹" in exc.value.message


def test_old_pack_payload_rejected(db_path):
    before = rulepack.status(db_path)
    rulepack.upgrade("RP-CLEAN", "v2", db_path=db_path)
    item, open_bin = _first_bad_item(db_path)
    with pytest.raises(ServiceError) as exc:
        quarantine.enter_item(
            item["id"], open_bin["id"], "旧版本号", db_path,
            pack_version=before["pack_version"],
        )
    assert exc.value.status_code == 409
    assert "旧包" in exc.value.message
    with pytest.raises(ServiceError) as exc2:
        quarantine.enter_item(
            item["id"], open_bin["id"], "旧指纹", db_path, pack_fp="deadbeef0000"
        )
    assert exc2.value.status_code == 409
    assert "旧包" in exc2.value.message
    row = quarantine.enter_item(
        item["id"], open_bin["id"], "现行载荷", db_path,
        pack_fp=before["rules_fp"], pack_version=before["pack_version"] + 1,
    )
    assert row["status"] == "待复核"


def test_concurrent_upgrade_single_winner(db_path):
    results = {"ok": 0, "conflict": 0, "messages": []}
    barrier = threading.Barrier(2)

    def worker(name):
        barrier.wait()
        try:
            rulepack.upgrade("RP-CLEAN", f"{name}升版", name, expect_version=1, db_path=db_path)
            results["ok"] += 1
        except ServiceError as exc:
            results["conflict"] += 1
            results["messages"].append(exc.message)

    t1 = threading.Thread(target=worker, args=("仓管甲",))
    t2 = threading.Thread(target=worker, args=("仓管乙",))
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    assert results["ok"] == 1
    assert results["conflict"] == 1
    assert results["messages"] and "刷新" in results["messages"][0]
    versions = [
        r["pack_version"] for r in rulepack.status(db_path)["ledger"] if r["pack_key"] == "RP-CLEAN"
    ]
    assert len(versions) == len(set(versions))
    assert rulepack.status(db_path)["pack_version"] == 2


def test_upgrade_failure_plain_language(db_path):
    with pytest.raises(ServiceError) as exc:
        rulepack.upgrade("", "空键", db_path=db_path)
    assert "不能空" in exc.value.message
    rulepack.upgrade("RP-CLEAN", "先到v2", db_path=db_path)
    with pytest.raises(ServiceError) as exc2:
        rulepack.upgrade("RP-CLEAN", "按旧页面升版", expect_version=1, db_path=db_path)
    assert exc2.value.status_code == 409
    assert "刷新" in exc2.value.message


def test_scaffolding_removed(db_path):
    import importlib

    for mod in (
        "app.services.rulepack_ver",
        "app.services.rulepack_ver_cutover",
        "app.services.rulepack_ver_dualwrite",
        "app.services.rulepack_ver_audit",
    ):
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module(mod)
    with get_db(db_path) as conn:
        rows = conn.execute(
            "SELECT key FROM meta WHERE key LIKE 'rulepack_ver_%'"
        ).fetchall()
    assert rows == []
