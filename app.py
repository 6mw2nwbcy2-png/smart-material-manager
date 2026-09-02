"""Smart Material Manager production-stable entrypoint.

Production rule:
- Streamlit Cloud always uses the central PostgreSQL DATABASE_URL.
- Local SQLite is allowed only when CI_LOCAL_DB=1 for automated tests.
- Schema changes are additive only (CREATE/ALTER). No production hard-delete is used.
- Orders are soft-deleted and can be restored from 관리자 설정.
"""
from pathlib import Path

SNAPSHOT = Path(__file__).with_name("app_snapshot.py")
source = SNAPSHOT.read_text(encoding="utf-8")

# -----------------------------------------------------------------------------
# 1) CENTRAL DB ONLY IN PRODUCTION + retrying connection
# -----------------------------------------------------------------------------
old_db_boot = "DATABASE_URL = get_database_url()\nUSE_POSTGRES = bool(DATABASE_URL)"
new_db_boot = r'''DATABASE_URL = get_database_url()
CI_LOCAL_DB = os.environ.get("CI_LOCAL_DB", "").strip() == "1"
USE_POSTGRES = bool(DATABASE_URL)

if not USE_POSTGRES and not CI_LOCAL_DB:
    st.error("중앙 DB 연결정보(DATABASE_URL)가 없습니다. 데이터 보호를 위해 로컬 DB로 임의 전환하지 않습니다.")
    st.info("Streamlit Cloud → Manage app → Settings → Secrets의 DATABASE_URL을 확인해주세요.")
    st.stop()


def db_connect():
    import time as _time
    last_error = None
    for attempt in range(5):
        try:
            return psycopg2.connect(
                dsn=DATABASE_URL,
                connect_timeout=10,
                application_name="smart-material-manager",
                keepalives=1,
                keepalives_idle=30,
                keepalives_interval=10,
                keepalives_count=3,
            )
        except psycopg2.OperationalError as exc:
            last_error = exc
            if attempt < 4:
                _time.sleep(1 + attempt)
    raise last_error
'''
if old_db_boot not in source:
    raise RuntimeError("DB bootstrap marker not found")
source = source.replace(old_db_boot, new_db_boot, 1)
source = source.replace("psycopg2.connect(DATABASE_URL)", "db_connect()")

# -----------------------------------------------------------------------------
# 2) ADDITIVE, NON-DESTRUCTIVE SCHEMA MIGRATIONS
# -----------------------------------------------------------------------------
persistence_schema = r'''

def ensure_persistent_schema():
    """Add data-safety columns/tables. Never DROP/TRUNCATE production data."""
    if USE_POSTGRES:
        with db_connect() as c:
            with c.cursor() as cur:
                cur.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS deleted_at TEXT DEFAULT ''")
                cur.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS deleted_by TEXT DEFAULT ''")
                cur.execute("ALTER TABLE transactions ADD COLUMN IF NOT EXISTS deleted_at TEXT DEFAULT ''")
                cur.execute("ALTER TABLE transactions ADD COLUMN IF NOT EXISTS deleted_by TEXT DEFAULT ''")
                cur.execute("ALTER TABLE transactions ADD COLUMN IF NOT EXISTS order_id INTEGER")
                cur.execute(
                    """CREATE TABLE IF NOT EXISTS order_attachments(
                        id SERIAL PRIMARY KEY,
                        order_id INTEGER NOT NULL,
                        file_name TEXT NOT NULL,
                        mime_type TEXT DEFAULT '',
                        file_size BIGINT DEFAULT 0,
                        file_data BYTEA NOT NULL,
                        created_at TEXT DEFAULT ''
                    )"""
                )
                cur.execute(
                    """CREATE TABLE IF NOT EXISTS data_change_log(
                        id BIGSERIAL PRIMARY KEY,
                        action TEXT NOT NULL,
                        entity_type TEXT NOT NULL,
                        entity_id TEXT DEFAULT '',
                        detail TEXT DEFAULT '',
                        changed_by TEXT DEFAULT '',
                        created_at TIMESTAMPTZ DEFAULT NOW()
                    )"""
                )
            c.commit()
    else:
        with sqlite3.connect(DB) as c:
            order_cols = {row[1] for row in c.execute("PRAGMA table_info(orders)").fetchall()}
            for name in ["deleted_at", "deleted_by"]:
                if name not in order_cols:
                    c.execute(f"ALTER TABLE orders ADD COLUMN {name} TEXT DEFAULT ''")

            tx_cols = {row[1] for row in c.execute("PRAGMA table_info(transactions)").fetchall()}
            for name, definition in [
                ("deleted_at", "TEXT DEFAULT ''"),
                ("deleted_by", "TEXT DEFAULT ''"),
                ("order_id", "INTEGER"),
            ]:
                if name not in tx_cols:
                    c.execute(f"ALTER TABLE transactions ADD COLUMN {name} {definition}")

            c.execute(
                """CREATE TABLE IF NOT EXISTS order_attachments(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id INTEGER NOT NULL,
                    file_name TEXT NOT NULL,
                    mime_type TEXT DEFAULT '',
                    file_size INTEGER DEFAULT 0,
                    file_data BLOB NOT NULL,
                    created_at TEXT DEFAULT ''
                )"""
            )
            c.execute(
                """CREATE TABLE IF NOT EXISTS data_change_log(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    action TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    entity_id TEXT DEFAULT '',
                    detail TEXT DEFAULT '',
                    changed_by TEXT DEFAULT '',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )"""
            )
            c.commit()


def log_change(action, entity_type, entity_id="", detail="", changed_by="관리자"):
    execute(
        "INSERT INTO data_change_log(action,entity_type,entity_id,detail,changed_by) VALUES(?,?,?,?,?)",
        (str(action), str(entity_type), str(entity_id), str(detail), str(changed_by)),
    )
'''
call_marker = "migrate_delivery_columns()\n\nseed()"
if call_marker not in source:
    raise RuntimeError("schema migration marker not found")
source = source.replace(
    call_marker,
    persistence_schema + "\n\nmigrate_delivery_columns()\nensure_persistent_schema()\n\nseed()",
    1,
)

# Soft-deleted rows must not affect normal screens/totals.
source = source.replace(
    "LEFT JOIN transactions t ON b.id=t.item_id",
    "LEFT JOIN transactions t ON b.id=t.item_id AND COALESCE(t.deleted_at,'')=''",
)
source = source.replace(
    "SELECT * FROM orders ORDER BY id DESC",
    "SELECT * FROM orders WHERE COALESCE(deleted_at,'')='' ORDER BY id DESC",
)
source = source.replace(
    "WHERE o.order_complete=0",
    "WHERE o.order_complete=0 AND COALESCE(o.deleted_at,'')=''",
)

# -----------------------------------------------------------------------------
# 3) STONE PAGE ROUTE
# -----------------------------------------------------------------------------
source = source.replace(
    'runpy.run_path("pages/stone_impl.py", run_name="__main__")',
    'runpy.run_path("pages/4_Stone.py", run_name="__main__")',
)
source = source.replace(
    'runpy.run_path("pages/stone_impl_v2.py", run_name="__main__")',
    'runpy.run_path("pages/4_Stone.py", run_name="__main__")',
)

# Clear DB mode indicator: production never silently falls back to SQLite.
source = source.replace(
    'st.caption("☁ 중앙 DB 연결" if USE_POSTGRES else "💻 로컬 SQLite 모드")',
    'st.caption("☁ 중앙 DB 연결 · 데이터 영구저장" if USE_POSTGRES else "🧪 CI 테스트 DB")',
    1,
)

# -----------------------------------------------------------------------------
# 4) ADMIN: bulk item editor + order status/delete/restore + password
# -----------------------------------------------------------------------------
admin_marker = 'elif menu == "관리자 설정":'
pos = source.find(admin_marker)
if pos >= 0:
    admin_block = r'''elif menu == "관리자 설정":
    st.subheader("관리자 설정")
    if not is_admin():
        st.warning("관리자 로그인 후 사용할 수 있습니다.")
    else:
        st.success("☁ 중앙 DB 영구저장 모드: 앱 업데이트와 데이터 저장소를 분리했습니다.")
        st.caption("삭제는 실제 데이터 삭제가 아니라 보관 처리되며, 아래 '삭제 발주서 복구'에서 되돌릴 수 있습니다.")

        st.markdown("### 예산 / 품목 관리")
        st.caption("철근·레미콘·타일·석재를 한 표에서 여러 행 추가/수정/삭제한 뒤 저장 버튼 한 번으로 반영합니다.")

        items = read("SELECT * FROM budget_items WHERE active=1 ORDER BY category,vendor,spec,item_name")
        edit_cols = ["id","category","vendor","item_name","spec","unit","budget_qty","tile_type","application_type","default_destination"]
        base = items[edit_cols].copy() if len(items) else pd.DataFrame(columns=edit_cols)

        edited = st.data_editor(
            base,
            use_container_width=True,
            hide_index=True,
            disabled=["id"],
            num_rows="dynamic",
            column_config={
                "id": None,
                "category": st.column_config.SelectboxColumn("공종", options=["철근","레미콘","타일","석재"], required=True),
                "vendor": st.column_config.TextColumn("협력사"),
                "item_name": st.column_config.TextColumn("품명", required=True),
                "spec": st.column_config.TextColumn("규격"),
                "unit": st.column_config.TextColumn("단위", required=True),
                "budget_qty": st.column_config.NumberColumn("예산수량", min_value=0.0, step=0.1),
                "tile_type": st.column_config.TextColumn("타일/석재구분"),
                "application_type": st.column_config.TextColumn("적용구분"),
                "default_destination": st.column_config.TextColumn("기본납품처"),
            },
            key="admin_bulk_budget_editor_v4",
        )

        if st.button("예산 / 품목 전체 저장", type="primary", key="admin_bulk_save_v4"):
            current_ids = set(items["id"].astype(int).tolist()) if len(items) else set()
            edited_ids = set()
            seen = set()
            errors = []

            for idx, r in edited.iterrows():
                category = str(r.get("category", "") or "").strip()
                item_name = str(r.get("item_name", "") or "").strip()
                spec = str(r.get("spec", "") or "").strip()
                unit = str(r.get("unit", "") or "").strip()
                vendor = str(r.get("vendor", "") or "").strip()
                tile_type = str(r.get("tile_type", "") or "").strip()
                application_type = str(r.get("application_type", "") or "").strip()
                default_destination = str(r.get("default_destination", "") or "").strip()
                budget_qty = float(r.get("budget_qty", 0) or 0)

                if not category and not item_name and not unit:
                    continue
                if not category or not item_name or not unit:
                    errors.append(f"{idx+1}행: 공종·품명·단위는 필수입니다.")
                    continue

                key = (category, item_name, spec)
                if key in seen:
                    errors.append(f"{idx+1}행: 같은 공종/품명/규격이 중복되었습니다.")
                    continue
                seen.add(key)

                if category == "타일" and not default_destination:
                    default_destination = calc_destination(tile_type, application_type)
                if category == "석재":
                    if not tile_type:
                        tile_type = "인조석"
                    if not default_destination:
                        default_destination = "현장"

                rid = r.get("id")
                if pd.notna(rid):
                    rid = int(rid)
                    edited_ids.add(rid)
                    execute(
                        """UPDATE budget_items
                           SET category=?,vendor=?,item_name=?,spec=?,unit=?,budget_qty=?,
                               tile_type=?,application_type=?,default_destination=?,active=1
                           WHERE id=?""",
                        (category,vendor,item_name,spec,unit,budget_qty,tile_type,
                         application_type,default_destination,rid),
                    )
                else:
                    dup = read(
                        "SELECT id FROM budget_items WHERE category=? AND item_name=? AND spec=? AND active=1",
                        (category,item_name,spec),
                    )
                    if len(dup):
                        errors.append(f"{idx+1}행: 이미 등록된 품목입니다.")
                        continue
                    execute(
                        """INSERT INTO budget_items(
                           category,vendor,item_name,spec,unit,budget_qty,
                           tile_type,application_type,default_destination,active)
                           VALUES(?,?,?,?,?,?,?,?,?,1)""",
                        (category,vendor,item_name,spec,unit,budget_qty,tile_type,
                         application_type,default_destination),
                    )

            if errors:
                st.error("저장하지 못한 행이 있습니다: " + " / ".join(errors))
            else:
                for rid in current_ids - edited_ids:
                    execute("UPDATE budget_items SET active=0 WHERE id=?", (rid,))
                    log_change("DEACTIVATE", "budget_item", rid, "관리자 품목관리에서 비활성 처리")
                st.success("예산 / 품목 전체 저장 완료")
                st.rerun()

        st.markdown("---")
        st.markdown("### 발주서 관리")
        st.caption("저장된 모든 공종 발주서를 관리자가 상태 변경하거나 삭제(보관)할 수 있습니다.")

        admin_orders = read(
            """SELECT id,order_no,category,vendor,order_date,partner_confirm,internal_approval,order_complete,note
               FROM orders
               WHERE COALESCE(deleted_at,'')=''
               ORDER BY id DESC LIMIT 300"""
        )

        if not len(admin_orders):
            st.info("저장된 발주서가 없습니다.")
        else:
            order_labels = {
                f"{r.order_no} | {r.category} | {r.vendor} | {r.order_date}": int(r.id)
                for _, r in admin_orders.iterrows()
            }
            selected_label = st.selectbox("관리할 발주서", list(order_labels.keys()), key="admin_order_select_v4")
            selected_id = order_labels[selected_label]
            selected_order = admin_orders[admin_orders.id == selected_id].iloc[0]

            st.write(
                f"**발주번호:** {selected_order.order_no}  ·  **공종:** {selected_order.category}  ·  "
                f"**협력사:** {selected_order.vendor}  ·  **발주일:** {selected_order.order_date}"
            )

            s1, s2, s3 = st.columns(3)
            admin_partner = s1.checkbox("협력사 확인", value=bool(selected_order.partner_confirm), key=f"admin_partner_{selected_id}")
            admin_approval = s2.checkbox("결재 완료", value=bool(selected_order.internal_approval), key=f"admin_approval_{selected_id}")
            admin_complete = s3.checkbox("발주 완료", value=bool(selected_order.order_complete), key=f"admin_complete_{selected_id}")

            a1, a2 = st.columns(2)
            if a1.button("발주 상태 저장", type="primary", key=f"admin_order_status_{selected_id}"):
                execute(
                    "UPDATE orders SET partner_confirm=?,internal_approval=?,order_complete=? WHERE id=?",
                    (int(admin_partner), int(admin_approval), int(admin_complete), selected_id),
                )
                log_change("STATUS_UPDATE", "order", selected_id, f"order_no={selected_order.order_no}")
                st.success("발주 상태 저장 완료")
                st.rerun()

            delete_confirm = a2.checkbox("삭제 확인", key=f"admin_order_delete_confirm_{selected_id}")
            if a2.button("발주서 삭제(보관)", key=f"admin_order_delete_{selected_id}"):
                if not delete_confirm:
                    st.warning("삭제 확인을 먼저 체크해주세요.")
                else:
                    deleted_at = pd.Timestamp.now().isoformat()
                    order_no = str(selected_order.order_no)
                    execute("UPDATE orders SET deleted_at=?,deleted_by=? WHERE id=?", (deleted_at,"관리자",selected_id))
                    execute(
                        "UPDATE transactions SET deleted_at=?,deleted_by=? WHERE tx_type='발주' AND note LIKE ?",
                        (deleted_at,"관리자",f"%{order_no}%"),
                    )
                    log_change("SOFT_DELETE", "order", selected_id, f"order_no={order_no}")
                    st.success(f"{order_no} 발주서를 삭제 보관함으로 이동했습니다. 데이터는 실제 삭제되지 않습니다.")
                    st.rerun()

        with st.expander("🗃 삭제 발주서 복구"):
            deleted_orders = read(
                """SELECT id,order_no,category,vendor,order_date,deleted_at
                   FROM orders
                   WHERE COALESCE(deleted_at,'')<>''
                   ORDER BY id DESC LIMIT 300"""
            )
            if not len(deleted_orders):
                st.caption("삭제 보관된 발주서가 없습니다.")
            else:
                restore_labels = {
                    f"{r.order_no} | {r.category} | {r.vendor} | 삭제 {r.deleted_at}": int(r.id)
                    for _, r in deleted_orders.iterrows()
                }
                restore_label = st.selectbox("복구할 발주서", list(restore_labels.keys()), key="admin_restore_order_select_v4")
                restore_id = restore_labels[restore_label]
                restore_row = deleted_orders[deleted_orders.id == restore_id].iloc[0]
                if st.button("발주서 복구", key=f"admin_restore_order_{restore_id}"):
                    order_no = str(restore_row.order_no)
                    execute("UPDATE orders SET deleted_at='',deleted_by='' WHERE id=?", (restore_id,))
                    execute(
                        "UPDATE transactions SET deleted_at='',deleted_by='' WHERE tx_type='발주' AND note LIKE ?",
                        (f"%{order_no}%",),
                    )
                    log_change("RESTORE", "order", restore_id, f"order_no={order_no}")
                    st.success(f"{order_no} 발주서를 복구했습니다.")
                    st.rerun()

        st.markdown("---")
        st.markdown("### 관리자 비밀번호 변경")
        p1 = st.text_input("새 비밀번호", type="password", key="admin_pw1_v4")
        p2 = st.text_input("새 비밀번호 확인", type="password", key="admin_pw2_v4")
        if st.button("비밀번호 변경", key="admin_pw_change_v4"):
            if len(p1) < 4:
                st.warning("4자리 이상 입력하세요.")
            elif p1 != p2:
                st.warning("비밀번호가 서로 다릅니다.")
            else:
                execute("UPDATE settings SET value=? WHERE key='admin_password'", (sha(p1),))
                log_change("PASSWORD_CHANGE", "settings", "admin_password", "관리자 비밀번호 변경")
                st.success("비밀번호 변경 완료")
'''
    source = source[:pos] + admin_block

exec(compile(source, str(SNAPSHOT), "exec"), globals(), globals())
