"""规则包：甲路切流账册（唯一工程形态，乙路双写两轨已下线）。

升版即把「包键 + 版本号 + 规则指纹」钉进 rulepack_ledger 账册，
并 CAS 拨动唯一钉点 rulepack_active_id；两名仓管同抢只有一人成。
清洗侧（入舱 / 套规则 / 复核放行 / 回炉）只读该账册：
指纹对不上拒洗，揣旧包版本号或旧指纹的载荷一样拒洗，失败全吐白话。
"""
from __future__ import annotations

import hashlib
import sqlite3

from app.db import get_db
from app.services.errors import ServiceError

READ_TRACK = "cutover_book"
ACTIVE_KEY = "rulepack_active_id"
GENESIS_PACK = "RP-CLEAN"

BADGE_OK = "规则包已钉"
BADGE_STALE = "规则包指纹不符"


def _meta_get(conn, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def _meta_set(conn, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


def live_rules_fp(conn) -> str:
    """现行清洗口径指纹：全部入舱规则按编码排序后取哈希。"""
    rows = conn.execute(
        """
        SELECT rule_code, quality_match, action, target_bin_code, enabled
        FROM policy_rules ORDER BY rule_code
        """
    ).fetchall()
    h = hashlib.sha256()
    for r in rows:
        h.update(
            "|".join(
                str(r[c])
                for c in ("rule_code", "quality_match", "action", "target_bin_code", "enabled")
            ).encode("utf-8")
        )
        h.update(b"\n")
    return h.hexdigest()[:12]


def _pinned_row(conn):
    active = _meta_get(conn, ACTIVE_KEY, "")
    if not active:
        return None
    return conn.execute(
        "SELECT * FROM rulepack_ledger WHERE id=?", (int(active),)
    ).fetchone()


def _ensure_genesis(conn) -> None:
    """账册为空时钉上创世版 v1（现行规则指纹），幂等。"""
    if _meta_get(conn, ACTIVE_KEY, ""):
        return
    fp = live_rules_fp(conn)
    try:
        cur = conn.execute(
            """
            INSERT INTO rulepack_ledger(pack_key, pack_version, rules_fp, actor, note)
            VALUES (?, 1, ?, 'system', '初始钉版')
            """,
            (GENESIS_PACK, fp),
        )
        _meta_set(conn, ACTIVE_KEY, str(cur.lastrowid))
    except sqlite3.IntegrityError:
        row = conn.execute(
            "SELECT id FROM rulepack_ledger WHERE pack_key=? AND pack_version=1",
            (GENESIS_PACK,),
        ).fetchone()
        _meta_set(conn, ACTIVE_KEY, str(row["id"]))


def ensure_seeded(db_path: str | None = None) -> None:
    with get_db(db_path) as conn:
        _ensure_genesis(conn)


def status(db_path: str | None = None) -> dict:
    """四屏共用的规则包口径：徽标 + 包版本号 + 落点行。"""
    with get_db(db_path) as conn:
        _ensure_genesis(conn)
        pinned = _pinned_row(conn)
        live_fp = live_rules_fp(conn)
        count = conn.execute("SELECT COUNT(*) AS c FROM rulepack_ledger").fetchone()["c"]
        ledger = conn.execute(
            "SELECT * FROM rulepack_ledger ORDER BY id DESC"
        ).fetchall()
        active = _meta_get(conn, ACTIVE_KEY, "")
    if pinned is None:  # pragma: no cover - 创世钉版兜底
        raise ServiceError("规则包账册是空的，还没钉版，请先升版钉死", 409)
    aligned = pinned["rules_fp"] == live_fp
    badge = BADGE_OK if aligned else BADGE_STALE
    landing = (
        f"切流账册#{pinned['id']} · {pinned['pack_key']} · "
        f"v{pinned['pack_version']} · 指纹 {pinned['rules_fp']}"
    )
    return {
        "read_track": READ_TRACK,
        "badge": badge,
        "aligned": aligned,
        "pack_key": pinned["pack_key"],
        "pack_version": pinned["pack_version"],
        "rules_fp": pinned["rules_fp"],
        "live_fp": live_fp,
        "pinned_by": pinned["actor"],
        "pinned_at": pinned["created_at"],
        "note": pinned["note"],
        "ledger_count": count,
        "landing": landing,
        "ledger": [
            {**dict(r), "active": str(r["id"]) == active} for r in ledger
        ],
    }


def upgrade(
    pack_key: str,
    note: str = "",
    actor: str = "admin",
    expect_version: int | None = None,
    db_path: str | None = None,
) -> dict:
    """升版钉死：一个事务里写账册行 + CAS 拨钉点，失败吐白话。"""
    pack_key = (pack_key or "").strip()
    if not pack_key:
        raise ServiceError("规则包键不能空，请填好再钉版")
    note = (note or "").strip()
    actor = (actor or "admin").strip() or "admin"
    new_ver = 0
    try:
        with get_db(db_path) as conn:
            _ensure_genesis(conn)
            live_fp = live_rules_fp(conn)
            cur_ver = conn.execute(
                "SELECT COALESCE(MAX(pack_version), 0) AS v FROM rulepack_ledger WHERE pack_key=?",
                (pack_key,),
            ).fetchone()["v"]
            new_ver = cur_ver + 1
            if expect_version is not None and int(expect_version) != cur_ver:
                raise ServiceError(
                    f"规则包 {pack_key} 已被升到 v{cur_ver}，你还按旧页面 "
                    f"v{expect_version} 升版，本次已回滚，请刷新后重试",
                    409,
                )
            old_active = _meta_get(conn, ACTIVE_KEY, "")
            cur = conn.execute(
                """
                INSERT INTO rulepack_ledger(pack_key, pack_version, rules_fp, actor, note)
                VALUES (?, ?, ?, ?, ?)
                """,
                (pack_key, new_ver, live_fp, actor, note),
            )
            new_id = str(cur.lastrowid)
            moved = conn.execute(
                "UPDATE meta SET value=? WHERE key=? AND value=?",
                (new_id, ACTIVE_KEY, old_active),
            )
            if moved.rowcount != 1:
                raise ServiceError(
                    "另一仓管刚改动了规则包钉点，本次升版已回滚，请刷新后重试",
                    409,
                )
    except sqlite3.IntegrityError:
        raise ServiceError(
            f"规则包 {pack_key} v{new_ver} 刚被另一仓管钉上，本次升版已回滚，请刷新后重试",
            409,
        )
    except sqlite3.OperationalError as exc:
        if "lock" in str(exc).lower():
            raise ServiceError(
                "规则包账册正被他人写入，本次升版没落账，请稍后重试",
                409,
            )
        raise ServiceError(f"规则包升版事务写失败：{exc}", 500)
    from app.services import audit as audit_svc

    audit_svc.write_event(
        "规则包升版",
        "rulepack",
        int(new_id),
        f"{pack_key} v{new_ver} 指纹{live_fp}",
        actor=actor,
        db_path=db_path,
    )
    return status(db_path)


def require_aligned(
    db_path: str | None = None,
    pack_fp: str | None = None,
    pack_version: int | None = None,
) -> None:
    """清洗闸门：指纹对不上拒洗，旧包载荷拒洗，全吐白话。"""
    st = status(db_path)
    if not st["aligned"]:
        raise ServiceError(
            f"规则包指纹对不上：账册钉着 {st['pack_key']} v{st['pack_version']}"
            f"（指纹 {st['rules_fp']}），现行规则指纹 {st['live_fp']}，"
            "请先升版钉死再清洗",
            409,
        )
    if pack_version is not None and int(pack_version) != st["pack_version"]:
        raise ServiceError(
            f"任务还带着旧规则包 v{pack_version}，账册已钉到 "
            f"v{st['pack_version']}，旧包载荷被拒",
            409,
        )
    if pack_fp and pack_fp != st["rules_fp"]:
        raise ServiceError(
            f"任务还带着旧规则包指纹 {pack_fp}，账册现行指纹 "
            f"{st['rules_fp']}，旧包载荷被拒",
            409,
        )


def audit_summary(db_path: str | None = None) -> dict:
    st = status(db_path)
    return {
        "title": "规则包",
        "read_track": READ_TRACK,
        "badge": st["badge"],
        "pack_key": st["pack_key"],
        "pack_version": st["pack_version"],
        "aligned": st["aligned"],
        "ledger_count": st["ledger_count"],
        "landing": st["landing"],
    }
