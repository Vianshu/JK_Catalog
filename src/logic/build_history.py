"""
Build History -- delta-based catalog undo.

Stores only what changed per build (CRM pending adds, serial shifts) --
not full table snapshots.  Each delta is typically <10 KB even for large
catalogs, so the last MAX_CHECKPOINTS builds are kept with negligible overhead.

Usage (called from CatalogBuildWorker after engine_run):
    from src.logic.build_history import save_checkpoint
    save_checkpoint(conn, username, engine_result["delta"])

Usage (called from BuildHistoryDialog):
    from src.logic.build_history import list_checkpoints, get_delta, restore_checkpoint
"""

import json
from src.utils.app_logger import get_logger

logger = get_logger(__name__)

MAX_CHECKPOINTS = 5

_CREATE_TABLE_SQL = """
IF NOT EXISTS (
    SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'build_history'
)
CREATE TABLE build_history (
    id             INT IDENTITY(1,1) PRIMARY KEY,
    build_time     DATETIME         DEFAULT GETDATE(),
    username       NVARCHAR(100),
    pages_affected INT              DEFAULT 0,
    crm_count      INT              DEFAULT 0,
    delta_json     NVARCHAR(MAX)
)
"""


def _ensure_table(conn):
    try:
        cursor = conn.cursor()
        cursor.execute(_CREATE_TABLE_SQL)
        conn.commit()
    except Exception as e:
        logger.warning(f"build_history: ensure_table failed: {e}")


def save_checkpoint(conn, username: str, delta: dict):
    """Persist a build delta and trim old checkpoints to MAX_CHECKPOINTS.

    Args:
        conn:     Active SQL Server connection to the catalog DB.
        username: Display name of the user who triggered the build.
        delta:    Dict returned by engine_run under the 'delta' key.
    """
    if not conn or not delta:
        return
    _ensure_table(conn)

    affected = delta.get("affected_count", 0)
    crm_adds = delta.get("crm_adds", {})
    crm_count = len(crm_adds)

    if affected == 0 and not crm_adds and not delta.get("serial_shifts"):
        return

    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO build_history (username, pages_affected, crm_count, delta_json) "
            "VALUES (?, ?, ?, ?)",
            (username or "unknown", affected, crm_count, json.dumps(delta, ensure_ascii=False))
        )
        cursor.execute(
            "DELETE FROM build_history WHERE id NOT IN ("
            "  SELECT TOP (?) id FROM build_history ORDER BY id DESC"
            ")",
            (MAX_CHECKPOINTS,)
        )
        conn.commit()
        logger.info(f"build_history: checkpoint saved (affected={affected}, CRMs={crm_count})")
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error(f"build_history.save_checkpoint error: {e}", exc_info=True)


def list_checkpoints(conn):
    """Return recent build checkpoints, newest first.

    Returns:
        List of tuples: (id, build_time, pages_affected, crm_count, username)
    """
    if not conn:
        return []
    _ensure_table(conn)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, build_time, pages_affected, crm_count, username "
            "FROM build_history ORDER BY id DESC"
        )
        return cursor.fetchall()
    except Exception as e:
        logger.error(f"build_history.list_checkpoints error: {e}")
        return []


def get_delta(conn, build_id: int) -> dict:
    """Return the delta dict for a specific build id."""
    if not conn:
        return {}
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT delta_json FROM build_history WHERE id=?", (build_id,))
        row = cursor.fetchone()
        if row and row[0]:
            return json.loads(row[0])
    except Exception as e:
        logger.error(f"build_history.get_delta error: {e}")
    return {}


def restore_checkpoint(conn, build_id: int) -> bool:
    """Reverse the effect of a build by applying its delta in reverse.

    Operations performed (all in one transaction):
      1. Remove CRM pending entries that this build added.
      2. Reverse serial shifts (swap old/new serial numbers back).

    Returns:
        True if restore succeeded, False otherwise.
    """
    delta = get_delta(conn, build_id)
    if not delta:
        logger.warning(f"build_history.restore_checkpoint: no delta for id={build_id}")
        return False

    try:
        cursor = conn.cursor()

        # 1. Remove CRM pending entries added by this build
        crm_adds = delta.get("crm_adds", {})
        for crm_name, serials in crm_adds.items():
            if not serials:
                continue
            placeholders = ",".join("?" * len(serials))
            cursor.execute(
                f"DELETE FROM report_data "
                f"WHERE crm_name=? AND serial_no IN ({placeholders}) AND status='pending'",
                [crm_name] + [str(s) for s in serials]
            )
            logger.debug(f"build_history: removed {len(serials)} pending entries for CRM '{crm_name}'")

        # 2. Reverse serial shifts
        for shift in delta.get("serial_shifts", []):
            old_sn = shift.get("old_serial")
            new_sn = shift.get("new_serial")
            key_parts = str(shift.get("key", "")).split("|")
            if len(key_parts) == 3 and old_sn and new_sn:
                group_name, sg_sn, page_no_str = key_parts
                try:
                    cursor.execute(
                        "UPDATE catalog_pages SET serial_no=? "
                        "WHERE TRIM(group_name)=? COLLATE Latin1_General_CI_AI "
                        "  AND CAST(sg_sn AS INTEGER)=CAST(? AS INTEGER) "
                        "  AND page_no=?",
                        (int(old_sn), group_name.strip(), sg_sn, int(page_no_str))
                    )
                except (ValueError, TypeError) as conv_err:
                    logger.warning(f"build_history: serial shift skip: {conv_err}")

        conn.commit()
        logger.info(f"build_history: restore of checkpoint {build_id} complete")
        return True

    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error(f"build_history.restore_checkpoint error: {e}", exc_info=True)
        return False
