import time

from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import declarative_base, sessionmaker

from config import CATEGORIES, DB_HOST, DB_NAME, DB_PASSWORD, DB_PORT, DB_USER, PRIORITIES, STATUSES

Base = declarative_base()


def build_db_url() -> str:
    # mysql+pymysql://user:pass@host:port/dbname?charset=utf8mb4
    return f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}?charset=utf8mb4"


engine = create_engine(build_db_url(), pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


LOOKUPS = {
    "category": ("category_id", "category_name", CATEGORIES),
    "priority": ("priority_id", "priority_name", PRIORITIES),
    "status": ("status_id", "status_name", STATUSES),
}


def db_retry(max_tries: int = 30, delay_s: float = 1.0) -> None:
    for _ in range(max_tries):
        try:
            with engine.connect() as conn:
                conn.exec_driver_sql("SELECT 1")
            return
        except OperationalError:
            time.sleep(delay_s)
    raise RuntimeError("Database is not reachable after retries")


def _insp():
    return inspect(engine)


def _has_table(table_name: str) -> bool:
    return _insp().has_table(table_name)


def _columns(table_name: str) -> set[str]:
    if not _has_table(table_name):
        return set()
    return {c["name"] for c in _insp().get_columns(table_name)}


def _rename_table(conn, old_name: str, new_name: str) -> None:
    if _has_table(old_name) and not _has_table(new_name):
        conn.exec_driver_sql(f"RENAME TABLE `{old_name}` TO `{new_name}`")


def _rename_column(conn, table_name: str, old_name: str, new_name: str) -> None:
    cols = _columns(table_name)
    if old_name in cols and new_name not in cols:
        conn.exec_driver_sql(f"ALTER TABLE `{table_name}` RENAME COLUMN `{old_name}` TO `{new_name}`")


def _add_column(conn, table_name: str, column_name: str, definition: str) -> None:
    if _has_table(table_name) and column_name not in _columns(table_name):
        conn.exec_driver_sql(f"ALTER TABLE `{table_name}` ADD COLUMN `{column_name}` {definition}")


def _drop_column(conn, table_name: str, column_name: str) -> None:
    if _has_table(table_name) and column_name in _columns(table_name):
        conn.exec_driver_sql(f"ALTER TABLE `{table_name}` DROP COLUMN `{column_name}`")


def _foreign_key_exists(table_name: str, column_name: str) -> bool:
    if not _has_table(table_name):
        return False
    return any(fk.get("constrained_columns") == [column_name] for fk in _insp().get_foreign_keys(table_name))


def _add_fk(conn, table_name: str, column_name: str, ref_table: str, ref_column: str, constraint_name: str) -> None:
    if not _has_table(table_name) or column_name not in _columns(table_name):
        return
    if not _has_table(ref_table) or ref_column not in _columns(ref_table):
        return
    if not _foreign_key_exists(table_name, column_name):
        conn.exec_driver_sql(
            f"""
            ALTER TABLE `{table_name}`
            ADD CONSTRAINT `{constraint_name}`
            FOREIGN KEY (`{column_name}`) REFERENCES `{ref_table}` (`{ref_column}`)
            """
        )


def _drop_unique_index_on_columns(conn, table_name: str, columns: list[str]) -> None:
    if not _has_table(table_name):
        return
    wanted = tuple(columns)
    for index in _insp().get_indexes(table_name):
        if index.get("unique") and tuple(index.get("column_names") or []) == wanted:
            conn.exec_driver_sql(f"ALTER TABLE `{table_name}` DROP INDEX `{index['name']}`")
            return


def _create_target_tables(conn) -> None:
    conn.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS `requester` (
            `requester_id` INT NOT NULL AUTO_INCREMENT,
            `requester_name` VARCHAR(255) NOT NULL,
            `requester_email` VARCHAR(255) NOT NULL,
            `requester_phone` VARCHAR(50) NULL,
            `telegram_chat_id` VARCHAR(64) NULL,
            `notification_preference` VARCHAR(20) NOT NULL DEFAULT 'BOTH',
            `created_at` DATETIME NULL DEFAULT CURRENT_TIMESTAMP,
            `updated_at` DATETIME NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (`requester_id`),
            KEY `ix_requester_email` (`requester_email`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    conn.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS `category` (
            `category_id` INT NOT NULL AUTO_INCREMENT,
            `category_name` VARCHAR(100) NOT NULL,
            `sort_order` INT NOT NULL DEFAULT 0,
            `created_at` DATETIME NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (`category_id`),
            UNIQUE KEY `uq_category_name` (`category_name`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    conn.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS `priority` (
            `priority_id` INT NOT NULL AUTO_INCREMENT,
            `priority_name` VARCHAR(50) NOT NULL,
            `sort_order` INT NOT NULL DEFAULT 0,
            `created_at` DATETIME NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (`priority_id`),
            UNIQUE KEY `uq_priority_name` (`priority_name`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    conn.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS `status` (
            `status_id` INT NOT NULL AUTO_INCREMENT,
            `status_name` VARCHAR(50) NOT NULL,
            `sort_order` INT NOT NULL DEFAULT 0,
            `created_at` DATETIME NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (`status_id`),
            UNIQUE KEY `uq_status_name` (`status_name`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )


def _create_admin_action_log(conn) -> None:
    if _has_table("admin_action_log") or not _has_table("admin"):
        return
    admin_pk = "admin_id" if "admin_id" in _columns("admin") else "id"
    ticket_pk = "ticket_id" if "ticket_id" in _columns("ticket") else "id"
    conn.exec_driver_sql(
        f"""
        CREATE TABLE `admin_action_log` (
            `log_id` INT NOT NULL AUTO_INCREMENT,
            `action_type` VARCHAR(100) NOT NULL,
            `action_reason` TEXT NULL,
            `admin_id` INT NOT NULL,
            `ticket_id` INT NULL,
            `action_time` DATETIME NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (`log_id`),
            KEY `ix_admin_action_log_admin_id` (`admin_id`),
            KEY `ix_admin_action_log_ticket_id` (`ticket_id`),
            CONSTRAINT `fk_admin_action_log_admin`
                FOREIGN KEY (`admin_id`) REFERENCES `admin` (`{admin_pk}`),
            CONSTRAINT `fk_admin_action_log_ticket`
                FOREIGN KEY (`ticket_id`) REFERENCES `ticket` (`{ticket_pk}`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )


def _rename_legacy_tables(conn) -> None:
    for legacy in ["ai_results", "health_check_templates"]:
        if _has_table(legacy):
            conn.exec_driver_sql(f"DROP TABLE `{legacy}`")

    for old_name, new_name in [
        ("admins", "admin"),
        ("technicians", "technician"),
        ("tickets", "ticket"),
        ("messages", "message"),
        ("attachments", "attachment"),
        ("health_checks", "health_check"),
        ("closure_confirmations", "closure_confirmation"),
    ]:
        _rename_table(conn, old_name, new_name)


def _rename_to_erd_columns(conn) -> None:
    for table_name, old_name, new_name in [
        ("requester", "id", "requester_id"),
        ("requester", "name", "requester_name"),
        ("requester", "email", "requester_email"),
        ("requester", "phone", "requester_phone"),
        ("technician", "id", "technician_id"),
        ("technician", "name", "technician_name"),
        ("technician", "email", "technician_email"),
        ("technician", "password_hash", "technician_password_hash"),
        ("technician", "is_active", "active_status"),
        ("technician", "availability", "availability_status"),
        ("admin", "id", "admin_id"),
        ("admin", "name", "admin_name"),
        ("admin", "email", "admin_email"),
        ("admin", "password_hash", "admin_password_hash"),
        ("admin", "is_active", "active_status"),
        ("category", "id", "category_id"),
        ("category", "name", "category_name"),
        ("priority", "id", "priority_id"),
        ("priority", "name", "priority_name"),
        ("status", "id", "status_id"),
        ("status", "name", "status_name"),
        ("ticket", "id", "ticket_id"),
        ("ticket", "token", "tracking_token"),
        ("ticket", "ai_suggested_solution", "ai_suggestion"),
        ("ticket", "ai_solution_suggestion", "ai_suggestion"),
        ("message", "id", "message_id"),
        ("message", "content", "message_text"),
        ("attachment", "id", "attachment_id"),
        ("attachment", "filename", "attachment_name"),
        ("attachment", "path", "attachment_path"),
        ("attachment", "sha256", "attachment_hash"),
        ("attachment", "created_at", "uploaded_at"),
        ("health_check", "id", "health_check_id"),
        ("health_check", "checklist_json", "health_check_checklist"),
        ("health_check", "result", "health_check_result"),
        ("health_check", "notes", "health_check_notes"),
        ("health_check", "created_at", "checked_at"),
        ("closure_confirmation", "id", "confirmation_id"),
        ("closure_confirmation", "signature_name", "e_sign"),
        ("closure_confirmation", "status", "confirmation_status"),
        ("admin_action_log", "id", "log_id"),
        ("admin_action_log", "action", "action_type"),
        ("admin_action_log", "details", "action_reason"),
        ("admin_action_log", "created_at", "action_time"),
    ]:
        _rename_column(conn, table_name, old_name, new_name)


def _ensure_missing_columns(conn) -> None:
    _add_column(conn, "technician", "technician_phone", "VARCHAR(50) NULL")
    _add_column(conn, "admin", "created_at", "DATETIME NULL DEFAULT CURRENT_TIMESTAMP")
    _add_column(conn, "admin", "updated_at", "DATETIME NULL DEFAULT CURRENT_TIMESTAMP")
    _add_column(conn, "technician", "created_at", "DATETIME NULL DEFAULT CURRENT_TIMESTAMP")
    _add_column(conn, "technician", "updated_at", "DATETIME NULL DEFAULT CURRENT_TIMESTAMP")

    _add_column(conn, "ticket", "requester_id", "INT NULL")
    _add_column(conn, "ticket", "category_id", "INT NULL")
    _add_column(conn, "ticket", "priority_id", "INT NULL")
    _add_column(conn, "ticket", "status_id", "INT NULL")
    _add_column(conn, "ticket", "ai_summary", "TEXT NULL")
    _add_column(conn, "ticket", "ai_suggestion", "TEXT NULL")
    _add_column(conn, "ticket", "ai_suggested_skill_group", "VARCHAR(100) NULL")
    _add_column(conn, "ticket", "ai_model", "VARCHAR(100) NULL")
    _add_column(conn, "ticket", "ai_raw_json", "TEXT NULL")
    _add_column(conn, "ticket", "health_questions_json", "TEXT NULL")

    _add_column(conn, "message", "requester_id", "INT NULL")
    _add_column(conn, "message", "technician_id", "INT NULL")
    _add_column(conn, "attachment", "uploaded_by_requester_id", "INT NULL")
    _add_column(conn, "attachment", "uploaded_by_technician_id", "INT NULL")
    _add_column(conn, "closure_confirmation", "requester_id", "INT NULL")
    _add_column(conn, "closure_confirmation", "requested_at", "DATETIME NULL")
    _add_column(conn, "closure_confirmation", "created_at", "DATETIME NULL DEFAULT CURRENT_TIMESTAMP")
    _add_column(conn, "closure_confirmation", "updated_at", "DATETIME NULL DEFAULT CURRENT_TIMESTAMP")
    _add_column(conn, "admin_action_log", "ticket_id", "INT NULL")


def _seed_lookup(conn, table_name: str, values: list[str]) -> None:
    id_col, name_col, _ = LOOKUPS[table_name]
    for sort_order, name in enumerate(values, start=1):
        conn.exec_driver_sql(
            f"""
            INSERT INTO `{table_name}` (`{name_col}`, `sort_order`)
            VALUES (%s, %s)
            ON DUPLICATE KEY UPDATE `sort_order` = VALUES(`sort_order`)
            """,
            (name, sort_order),
        )


def _seed_lookups_from_ticket(conn) -> None:
    if not _has_table("ticket"):
        return
    for table_name, legacy_column in [("category", "category"), ("priority", "priority"), ("status", "status")]:
        if legacy_column not in _columns("ticket"):
            continue
        _, name_col, _ = LOOKUPS[table_name]
        values = conn.exec_driver_sql(
            f"""
            SELECT DISTINCT `{legacy_column}`
            FROM `ticket`
            WHERE `{legacy_column}` IS NOT NULL AND TRIM(`{legacy_column}`) <> ''
            """
        ).scalars()
        for value in values:
            conn.exec_driver_sql(
                f"INSERT IGNORE INTO `{table_name}` (`{name_col}`, `sort_order`) VALUES (%s, 999)",
                (value,),
            )


def _lookup_id(conn, table_name: str, name: str) -> int:
    id_col, name_col, _ = LOOKUPS[table_name]
    lookup_id = conn.exec_driver_sql(
        f"SELECT `{id_col}` FROM `{table_name}` WHERE `{name_col}` = %s LIMIT 1",
        (name,),
    ).scalar()
    if lookup_id is None:
        conn.exec_driver_sql(
            f"INSERT INTO `{table_name}` (`{name_col}`, `sort_order`) VALUES (%s, 999)",
            (name,),
        )
        lookup_id = conn.exec_driver_sql("SELECT LAST_INSERT_ID()").scalar()
    return int(lookup_id)


def _migrate_requesters(conn) -> None:
    if not _has_table("ticket") or "requester_id" not in _columns("ticket"):
        return

    ticket_pk = "ticket_id" if "ticket_id" in _columns("ticket") else "id"
    if {"requester_name", "requester_email"}.issubset(_columns("ticket")):
        rows = conn.exec_driver_sql(
            f"""
            SELECT
                `{ticket_pk}` AS ticket_pk,
                `requester_name`,
                `requester_email`,
                `requester_phone`,
                `requester_telegram_chat_id`,
                `requester_notification_preference`
            FROM `ticket`
            WHERE `requester_id` IS NULL
            ORDER BY `{ticket_pk}`
            """
        ).mappings()
        for row in rows:
            conn.exec_driver_sql(
                """
                INSERT INTO `requester`
                    (`requester_name`, `requester_email`, `requester_phone`,
                     `telegram_chat_id`, `notification_preference`, `created_at`, `updated_at`)
                VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """,
                (
                    row["requester_name"] or "Unknown Requester",
                    row["requester_email"] or f"unknown+ticket{row['ticket_pk']}@local.invalid",
                    row["requester_phone"],
                    row["requester_telegram_chat_id"],
                    row["requester_notification_preference"] or "BOTH",
                ),
            )
            requester_id = conn.exec_driver_sql("SELECT LAST_INSERT_ID()").scalar()
            conn.exec_driver_sql(
                f"UPDATE `ticket` SET `requester_id` = %s WHERE `{ticket_pk}` = %s",
                (requester_id, row["ticket_pk"]),
            )

    null_rows = conn.exec_driver_sql(
        f"SELECT `{ticket_pk}` AS ticket_pk FROM `ticket` WHERE `requester_id` IS NULL"
    ).mappings()
    for row in null_rows:
        conn.exec_driver_sql(
            """
            INSERT INTO `requester`
                (`requester_name`, `requester_email`, `notification_preference`, `created_at`, `updated_at`)
            VALUES (%s, %s, 'BOTH', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            ("Unknown Requester", f"unknown+ticket{row['ticket_pk']}@local.invalid"),
        )
        requester_id = conn.exec_driver_sql("SELECT LAST_INSERT_ID()").scalar()
        conn.exec_driver_sql(
            f"UPDATE `ticket` SET `requester_id` = %s WHERE `{ticket_pk}` = %s",
            (requester_id, row["ticket_pk"]),
        )


def _migrate_ticket_lookups(conn) -> None:
    if not _has_table("ticket"):
        return

    fallback_ids = {
        "category": _lookup_id(conn, "category", "Other"),
        "priority": _lookup_id(conn, "priority", "Medium"),
        "status": _lookup_id(conn, "status", "NEW"),
    }
    for table_name, legacy_column in [("category", "category"), ("priority", "priority"), ("status", "status")]:
        id_col, name_col, _ = LOOKUPS[table_name]
        ticket_fk = f"{table_name}_id"
        if legacy_column in _columns("ticket"):
            conn.exec_driver_sql(
                f"""
                UPDATE `ticket` t
                JOIN `{table_name}` l ON l.`{name_col}` = COALESCE(NULLIF(TRIM(t.`{legacy_column}`), ''), %s)
                SET t.`{ticket_fk}` = l.`{id_col}`
                WHERE t.`{ticket_fk}` IS NULL
                """,
                ({"category": "Other", "priority": "Medium", "status": "NEW"}[table_name],),
            )
        conn.exec_driver_sql(
            f"UPDATE `ticket` SET `{ticket_fk}` = %s WHERE `{ticket_fk}` IS NULL",
            (fallback_ids[table_name],),
        )


def _migrate_message_senders(conn) -> None:
    if not _has_table("message") or "author_role" not in _columns("message"):
        return
    conn.exec_driver_sql(
        """
        UPDATE `message` m
        JOIN `ticket` t ON t.`ticket_id` = m.`ticket_id`
        SET m.`requester_id` = t.`requester_id`
        WHERE m.`requester_id` IS NULL AND m.`author_role` = 'Requester'
        """
    )
    conn.exec_driver_sql(
        """
        UPDATE `message`
        SET `technician_id` = `author_id`
        WHERE `technician_id` IS NULL AND `author_role` = 'Technician' AND `author_id` IS NOT NULL
        """
    )


def _migrate_attachment_uploaders(conn) -> None:
    if not _has_table("attachment") or "uploaded_by_role" not in _columns("attachment"):
        return
    conn.exec_driver_sql(
        """
        UPDATE `attachment` a
        JOIN `ticket` t ON t.`ticket_id` = a.`ticket_id`
        SET a.`uploaded_by_requester_id` = t.`requester_id`
        WHERE a.`uploaded_by_requester_id` IS NULL AND a.`uploaded_by_role` = 'Requester'
        """
    )
    conn.exec_driver_sql(
        """
        UPDATE `attachment`
        SET `uploaded_by_technician_id` = `uploaded_by_id`
        WHERE `uploaded_by_technician_id` IS NULL
          AND `uploaded_by_role` = 'Technician'
          AND `uploaded_by_id` IS NOT NULL
        """
    )


def _migrate_closure_requesters(conn) -> None:
    if not _has_table("closure_confirmation"):
        return
    conn.exec_driver_sql(
        """
        UPDATE `closure_confirmation` c
        JOIN `ticket` t ON t.`ticket_id` = c.`ticket_id`
        SET c.`requester_id` = t.`requester_id`
        WHERE c.`requester_id` IS NULL
        """
    )


def _migrate_admin_logs(conn) -> None:
    if not _has_table("admin_action_log"):
        return
    cols = _columns("admin_action_log")
    if {"target_type", "target_id", "ticket_id"}.issubset(cols):
        conn.exec_driver_sql(
            """
            UPDATE `admin_action_log`
            SET `ticket_id` = `target_id`
            WHERE `ticket_id` IS NULL AND `target_type` = 'ticket'
            """
        )


def _finalize_erd_schema(conn) -> None:
    if _has_table("ticket"):
        for col in ["requester_id", "category_id", "priority_id", "status_id"]:
            if col in _columns("ticket"):
                conn.exec_driver_sql(f"ALTER TABLE `ticket` MODIFY COLUMN `{col}` INT NOT NULL")
        for legacy_col in [
            "requester_name",
            "requester_email",
            "requester_phone",
            "requester_telegram_chat_id",
            "requester_notification_preference",
            "category",
            "priority",
            "status",
        ]:
            _drop_column(conn, "ticket", legacy_col)

    if _has_table("closure_confirmation") and "requester_id" in _columns("closure_confirmation"):
        _drop_unique_index_on_columns(conn, "closure_confirmation", ["ticket_id"])
        conn.exec_driver_sql("ALTER TABLE `closure_confirmation` MODIFY COLUMN `requester_id` INT NOT NULL")

    for table_name, col in [("message", "author_role"), ("message", "author_id")]:
        _drop_column(conn, table_name, col)
    for table_name, col in [("attachment", "uploaded_by_role"), ("attachment", "uploaded_by_id")]:
        _drop_column(conn, table_name, col)
    for col in ["target_type", "target_id"]:
        _drop_column(conn, "admin_action_log", col)

    _add_fk(conn, "ticket", "requester_id", "requester", "requester_id", "fk_ticket_requester")
    _add_fk(conn, "ticket", "category_id", "category", "category_id", "fk_ticket_category")
    _add_fk(conn, "ticket", "priority_id", "priority", "priority_id", "fk_ticket_priority")
    _add_fk(conn, "ticket", "status_id", "status", "status_id", "fk_ticket_status")
    _add_fk(conn, "message", "requester_id", "requester", "requester_id", "fk_message_requester")
    _add_fk(conn, "message", "technician_id", "technician", "technician_id", "fk_message_technician")
    _add_fk(conn, "attachment", "uploaded_by_requester_id", "requester", "requester_id", "fk_attachment_requester")
    _add_fk(
        conn,
        "attachment",
        "uploaded_by_technician_id",
        "technician",
        "technician_id",
        "fk_attachment_technician",
    )
    _add_fk(conn, "closure_confirmation", "requester_id", "requester", "requester_id", "fk_closure_requester")
    _add_fk(conn, "admin_action_log", "ticket_id", "ticket", "ticket_id", "fk_admin_action_log_ticket")


def migrate_schema() -> None:
    with engine.begin() as conn:
        _rename_legacy_tables(conn)
        _create_target_tables(conn)
        _rename_to_erd_columns(conn)
        _create_admin_action_log(conn)
        _ensure_missing_columns(conn)
        for table_name, (_, _, values) in LOOKUPS.items():
            _seed_lookup(conn, table_name, values)
        _seed_lookups_from_ticket(conn)
        _migrate_requesters(conn)
        _migrate_ticket_lookups(conn)
        _migrate_message_senders(conn)
        _migrate_attachment_uploaders(conn)
        _migrate_closure_requesters(conn)
        _migrate_admin_logs(conn)
        _finalize_erd_schema(conn)
