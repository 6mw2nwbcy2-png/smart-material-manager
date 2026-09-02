"""Database-level immutability rules for production central PostgreSQL.

Saved budget master data is append-only. The only fields that remain editable are
operational schedule metadata (planned_delivery_date, storage_location).
Saved material-use transactions (tx_type='투입') are immutable and cannot be updated
or deleted by any application code using the same database role.

The protection DDL is installed only when missing. Normal Streamlit reruns perform a
lightweight trigger-existence check instead of repeatedly dropping/creating triggers,
which avoids unnecessary table locks under concurrent users.
"""
from contextlib import closing
import psycopg2

_TRIGGER_NAMES = {
    "smm_budget_item_immutable",
    "smm_budget_item_no_truncate",
    "smm_used_transaction_immutable",
}


def _installed(cur):
    cur.execute(
        """SELECT tgname FROM pg_trigger
           WHERE NOT tgisinternal
             AND tgname IN (
                 'smm_budget_item_immutable',
                 'smm_budget_item_no_truncate',
                 'smm_used_transaction_immutable'
             )"""
    )
    return {row[0] for row in cur.fetchall()} == _TRIGGER_NAMES


def apply_central_db_protection(database_url: str):
    if not str(database_url or "").strip():
        return False, "중앙 DB URL 없음"

    sql = r'''
CREATE OR REPLACE FUNCTION smm_protect_budget_item()
RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION '저장된 예산/품목은 삭제할 수 없습니다.';
    END IF;

    IF OLD.category IS DISTINCT FROM NEW.category
       OR OLD.vendor IS DISTINCT FROM NEW.vendor
       OR OLD.item_name IS DISTINCT FROM NEW.item_name
       OR OLD.spec IS DISTINCT FROM NEW.spec
       OR OLD.unit IS DISTINCT FROM NEW.unit
       OR OLD.budget_qty IS DISTINCT FROM NEW.budget_qty
       OR OLD.tile_type IS DISTINCT FROM NEW.tile_type
       OR OLD.application_type IS DISTINCT FROM NEW.application_type
       OR OLD.default_destination IS DISTINCT FROM NEW.default_destination
       OR OLD.active IS DISTINCT FROM NEW.active THEN
        RAISE EXCEPTION '저장된 예산/품목의 핵심 내역은 수정할 수 없습니다.';
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS smm_budget_item_immutable ON budget_items;
CREATE TRIGGER smm_budget_item_immutable
BEFORE UPDATE OR DELETE ON budget_items
FOR EACH ROW EXECUTE FUNCTION smm_protect_budget_item();

CREATE OR REPLACE FUNCTION smm_protect_budget_truncate()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION '예산/품목 전체 삭제는 허용되지 않습니다.';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS smm_budget_item_no_truncate ON budget_items;
CREATE TRIGGER smm_budget_item_no_truncate
BEFORE TRUNCATE ON budget_items
FOR EACH STATEMENT EXECUTE FUNCTION smm_protect_budget_truncate();

CREATE OR REPLACE FUNCTION smm_protect_used_transaction()
RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.tx_type = '투입' THEN
            RAISE EXCEPTION '저장된 투입내역은 삭제할 수 없습니다.';
        END IF;
        RETURN OLD;
    END IF;

    IF TG_OP = 'UPDATE' AND (OLD.tx_type = '투입' OR NEW.tx_type = '투입') THEN
        RAISE EXCEPTION '저장된 투입내역은 수정할 수 없습니다.';
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS smm_used_transaction_immutable ON transactions;
CREATE TRIGGER smm_used_transaction_immutable
BEFORE UPDATE OR DELETE ON transactions
FOR EACH ROW EXECUTE FUNCTION smm_protect_used_transaction();
'''

    try:
        with closing(psycopg2.connect(
            database_url,
            connect_timeout=7,
            application_name="smart-material-manager-protection",
            keepalives=1,
            keepalives_idle=30,
            keepalives_interval=10,
            keepalives_count=3,
        )) as conn:
            with conn.cursor() as cur:
                if _installed(cur):
                    return True, "보호 적용 확인"

                # Only one app session installs/repairs protection at a time.
                cur.execute("SELECT pg_advisory_xact_lock(77120260902)")
                if not _installed(cur):
                    cur.execute(sql)
            conn.commit()
        return True, "보호 적용 완료"
    except Exception:
        return False, "중앙 DB 보호장치 적용 실패"
