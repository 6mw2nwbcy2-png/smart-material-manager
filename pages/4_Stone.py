"""Stone production wrapper.

- Production uses the central PostgreSQL DATABASE_URL only.
- SQLite is allowed only when CI_LOCAL_DB=1 for automated tests.
- Keeps the feature-rich stone order UI and attachments.
- Deletes are soft-deletes so order data and attachments are never physically lost.
"""
from pathlib import Path

SRC = Path(__file__).with_name("stone_impl_v2.py")
source = SRC.read_text(encoding="utf-8")

# -----------------------------------------------------------------------------
# CENTRAL DB bootstrap with retry. CI may explicitly use local SQLite.
# -----------------------------------------------------------------------------
start = source.index("DATABASE_URL = get_database_url()")
end = source.index("def seed_stone_items():")

central_bootstrap = r'''DATABASE_URL = get_database_url()
CI_LOCAL_DB = os.environ.get("CI_LOCAL_DB", "").strip() == "1"
USE_POSTGRES = bool(DATABASE_URL)

if not USE_POSTGRES and not CI_LOCAL_DB:
    st.error("중앙 DB에 연결되지 않았습니다. 데이터 보호를 위해 로컬 DB로 임의 전환하지 않습니다.")
    st.stop()


def db_connect():
    import time as _time
    last_error = None
    for attempt in range(5):
        try:
            return psycopg2.connect(
                dsn=DATABASE_URL,
                connect_timeout=10,
                application_name="smart-material-manager-stone",
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


def _pg_sql(sql):
    return sql.replace("?", "%s")


def execute(sql, params=()):
    if USE_POSTGRES:
        with db_connect() as c:
            with c.cursor() as cur:
                cur.execute(_pg_sql(sql), params)
            c.commit()
    else:
        with sqlite3.connect(DB) as c:
            c.execute(sql, params)
            c.commit()


def read(sql, params=()):
    if USE_POSTGRES:
        with db_connect() as c:
            return pd.read_sql_query(_pg_sql(sql), c, params=params)
    with sqlite3.connect(DB) as c:
        return pd.read_sql_query(sql, c, params=params)


def ensure_schema():
    if USE_POSTGRES:
        with db_connect() as c:
            with c.cursor() as cur:
                for name, definition in [
                    ("delivery_recipient", "TEXT DEFAULT ''"),
                    ("delivery_phone", "TEXT DEFAULT ''"),
                    ("delivery_address", "TEXT DEFAULT ''"),
                    ("storage_location", "TEXT DEFAULT ''"),
                ]:
                    cur.execute(f"ALTER TABLE order_lines ADD COLUMN IF NOT EXISTS {name} {definition}")
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
            c.execute("""CREATE TABLE IF NOT EXISTS budget_items(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                vendor TEXT DEFAULT '',
                item_name TEXT NOT NULL,
                spec TEXT DEFAULT '',
                unit TEXT NOT NULL,
                budget_qty REAL DEFAULT 0,
                tile_type TEXT DEFAULT '',
                application_type TEXT DEFAULT '',
                default_destination TEXT DEFAULT '',
                active INTEGER DEFAULT 1
            )""")
            c.execute("""CREATE TABLE IF NOT EXISTS transactions(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tx_date TEXT NOT NULL,
                item_id INTEGER NOT NULL,
                tx_type TEXT NOT NULL,
                qty REAL NOT NULL,
                destination TEXT DEFAULT '',
                note TEXT DEFAULT '',
                input_user TEXT DEFAULT ''
            )""")
            c.execute("""CREATE TABLE IF NOT EXISTS orders(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_no TEXT UNIQUE,
                category TEXT NOT NULL,
                vendor TEXT DEFAULT '',
                order_date TEXT NOT NULL,
                partner_confirm INTEGER DEFAULT 0,
                internal_approval INTEGER DEFAULT 0,
                order_complete INTEGER DEFAULT 0,
                note TEXT DEFAULT ''
            )""")
            c.execute("""CREATE TABLE IF NOT EXISTS order_lines(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                item_id INTEGER NOT NULL,
                qty REAL NOT NULL,
                requested_delivery_date TEXT DEFAULT '',
                destination TEXT DEFAULT ''
            )""")
            order_line_cols = {row[1] for row in c.execute("PRAGMA table_info(order_lines)").fetchall()}
            for name in ["delivery_recipient", "delivery_phone", "delivery_address", "storage_location"]:
                if name not in order_line_cols:
                    c.execute(f"ALTER TABLE order_lines ADD COLUMN {name} TEXT DEFAULT ''")
            order_cols = {row[1] for row in c.execute("PRAGMA table_info(orders)").fetchall()}
            for name in ["deleted_at", "deleted_by"]:
                if name not in order_cols:
                    c.execute(f"ALTER TABLE orders ADD COLUMN {name} TEXT DEFAULT ''")
            tx_cols = {row[1] for row in c.execute("PRAGMA table_info(transactions)").fetchall()}
            for name, definition in [("deleted_at", "TEXT DEFAULT ''"), ("deleted_by", "TEXT DEFAULT ''"), ("order_id", "INTEGER")]:
                if name not in tx_cols:
                    c.execute(f"ALTER TABLE transactions ADD COLUMN {name} {definition}")
            c.execute("""CREATE TABLE IF NOT EXISTS order_attachments(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                file_name TEXT NOT NULL,
                mime_type TEXT DEFAULT '',
                file_size INTEGER DEFAULT 0,
                file_data BLOB NOT NULL,
                created_at TEXT DEFAULT ''
            )""")
            c.execute("""CREATE TABLE IF NOT EXISTS data_change_log(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                entity_id TEXT DEFAULT '',
                detail TEXT DEFAULT '',
                changed_by TEXT DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )""")
            c.commit()


def log_change(action, entity_type, entity_id="", detail="", changed_by="관리자"):
    execute(
        "INSERT INTO data_change_log(action,entity_type,entity_id,detail,changed_by) VALUES(?,?,?,?,?)",
        (str(action),str(entity_type),str(entity_id),str(detail),str(changed_by)),
    )

'''
source = source[:start] + central_bootstrap + source[end:]

# Deleted order transactions must not count in stone totals.
source = source.replace(
    "LEFT JOIN transactions t ON b.id=t.item_id",
    "LEFT JOIN transactions t ON b.id=t.item_id AND COALESCE(t.deleted_at,'')=''",
)

# Items/budget are managed only in global 관리자 설정.
admin_start_marker = '''# --------------------------------------------------
# 관리자: 예산 / 품목 관리
# --------------------------------------------------'''
admin_end_marker = 'st.markdown("---")\nst.markdown("### 석재 현황")'
a = source.find(admin_start_marker)
b = source.find(admin_end_marker)
if a >= 0 and b > a:
    source = source[:a] + source[b:]

# Remove old partner item-registration form.
partner_start_marker = '''# --------------------------------------------------
# 협력사 품목 등록: 폼 제출 전에는 아무것도 DB에 저장하지 않음
# --------------------------------------------------'''
partner_end_marker = '''# --------------------------------------------------
# 투입내역: 입력 중에는 저장하지 않고 '저장' 시에만 DB 반영
# --------------------------------------------------'''
a = source.find(partner_start_marker)
b = source.find(partner_end_marker)
if a >= 0 and b > a:
    source = source[:a] + source[b:]

# Replace vendor-dependent order block with direct vendor input + multi-file attachments.
order_start = source.find('st.markdown("### 석재 발주서 작성")')
order_end = source.find('if st.session_state.get("stone_last_pdf"):', order_start)
order_block = r'''st.markdown("### 협력사 석재 발주서")
st.info("협력사명과 발주수량을 입력하고, 납품정보 및 도해도/첨부파일을 추가한 뒤 마지막 저장 버튼을 눌러주세요.")

if len(df):
    with st.form("stone_order_form_v4"):
        vendor = st.text_input("협력사명", placeholder="예: ○○석재")
        req = df[["id","item_name","spec","stone_type","unit","budget_qty","ordered"]].copy()
        req.columns = ["id","품명","규격","석재구분","단위","예산","누적발주"]
        req["발주수량"] = 0.0
        req["납품요청일"] = date.today()
        st.markdown("#### 품목 선택")
        req_edit = st.data_editor(
            req, use_container_width=True, hide_index=True,
            disabled=["id","품명","규격","석재구분","단위","예산","누적발주"],
            column_config={
                "id": None,
                "발주수량": st.column_config.NumberColumn("발주수량", min_value=0.0, step=0.1),
                "납품요청일": st.column_config.DateColumn("납품요청일", format="YYYY-MM-DD"),
            },
            key="stone_multi_order_v4",
        )
        st.markdown("#### 납품 정보")
        delivery_type = st.radio("납품구분", ["현장","기타"], horizontal=True, key="stone_delivery_type_v4")
        d1, d2 = st.columns(2)
        delivery_recipient = d1.text_input("받는 사람")
        delivery_phone = d2.text_input("연락처")
        site_address_df = read("SELECT value FROM settings WHERE key='site_address'")
        default_site_address = str(site_address_df.iloc[0]["value"]) if len(site_address_df) else ""
        delivery_address = st.text_input("현장 주소" if delivery_type == "현장" else "납품 주소", value=default_site_address if delivery_type == "현장" else "")
        c1, c2 = st.columns(2)
        order_date = c1.date_input("발주일", date.today())
        order_note = c2.text_input("발주 비고")
        st.markdown("#### 도해도 / 첨부파일")
        st.caption("PDF, Excel(XLS/XLSX), CAD(DWG/DXF), 이미지 파일을 여러 개 동시에 첨부할 수 있습니다.")
        attachments = st.file_uploader(
            "도해도 및 첨부파일 선택",
            type=["pdf","xls","xlsx","dwg","dxf","png","jpg","jpeg","webp","bmp","tif","tiff"],
            accept_multiple_files=True,
            key="stone_order_attachments_v4",
        )
        save_order = st.form_submit_button("선택 품목 일괄 발주 + PDF 생성", type="primary")

    if save_order:
        selected = req_edit[req_edit["발주수량"] > 0].copy()
        if not vendor.strip():
            st.warning("협력사명을 입력해주세요.")
        elif not len(selected):
            st.warning("발주수량을 입력한 품목이 없습니다.")
        elif not delivery_recipient.strip() or not delivery_phone.strip() or not delivery_address.strip():
            st.warning("받는 사람·연락처·납품 주소를 모두 입력해주세요.")
        else:
            order_no = next_order_no(order_date)
            execute(
                "INSERT INTO orders(order_no,category,vendor,order_date,partner_confirm,internal_approval,order_complete,note) VALUES(?,?,?,?,0,0,0,?)",
                (order_no,CATEGORY,vendor.strip(),str(order_date),order_note.strip()),
            )
            oid = int(read("SELECT id FROM orders WHERE order_no=?", (order_no,)).iloc[0]["id"])
            for _, r in selected.iterrows():
                item_id = int(r["id"])
                qty = float(r["발주수량"])
                delivery_date = pd.to_datetime(r["납품요청일"]).date().isoformat()
                execute(
                    """INSERT INTO order_lines(order_id,item_id,qty,requested_delivery_date,destination,
                           delivery_recipient,delivery_phone,delivery_address)
                       VALUES(?,?,?,?,?,?,?,?)""",
                    (oid,item_id,qty,delivery_date,delivery_type,delivery_recipient.strip(),delivery_phone.strip(),delivery_address.strip()),
                )
                execute(
                    "INSERT INTO transactions(tx_date,item_id,tx_type,qty,destination,note,input_user,order_id) VALUES(?,?,?,?,?,?,?,?)",
                    (str(order_date),item_id,"발주",qty,delivery_type,f"발주서 {order_no}",vendor.strip(),oid),
                )
            save_attachments(oid, attachments)
            log_change("CREATE", "order", oid, f"order_no={order_no}; attachments={len(attachments or [])}", vendor.strip())
            lines = read(
                """SELECT b.item_name,b.spec,b.unit,b.tile_type AS stone_type,
                          ol.qty,ol.destination,ol.requested_delivery_date,
                          ol.delivery_recipient,ol.delivery_phone,ol.delivery_address
                   FROM order_lines ol JOIN budget_items b ON ol.item_id=b.id
                   WHERE ol.order_id=? ORDER BY ol.requested_delivery_date,ol.id""",
                (oid,),
            )
            order_row = read("SELECT * FROM orders WHERE id=?", (oid,)).iloc[0]
            st.session_state["stone_last_pdf"] = make_pdf(order_row, lines)
            st.session_state["stone_last_pdf_name"] = f"{order_no}_석재발주서.pdf"
            st.success(f"{len(selected)}개 품목 발주 완료 / 첨부 {len(attachments or [])}개")
            st.rerun()
else:
    st.warning("등록된 석재 품목이 없습니다. 관리자가 '관리자 설정 → 예산 / 품목 관리'에서 석재 품목을 먼저 등록해주세요.")

'''
if order_start >= 0 and order_end > order_start:
    source = source[:order_start] + order_block + source[order_end:]

# Recent orders: approval + SOFT delete. Attachments/order lines stay intact forever.
recent_start = source.find('st.markdown("### 최근 석재 발주 / 도해도")')
if recent_start >= 0:
    recent_block = r'''st.markdown("### 최근 석재 발주 / 도해도")
recent = read(
    "SELECT id,order_no,vendor,order_date,partner_confirm,internal_approval,order_complete,note FROM orders WHERE category=? AND COALESCE(deleted_at,'')='' ORDER BY id DESC LIMIT 50",
    (CATEGORY,),
)
if not len(recent):
    st.info("등록된 석재 발주가 없습니다.")
else:
    for _, order in recent.iterrows():
        status = (
            "발주완료" if int(order["order_complete"] or 0)
            else "결재완료" if int(order["internal_approval"] or 0)
            else "협력사 확인완료" if int(order["partner_confirm"] or 0)
            else "결재/확인중"
        )
        with st.expander(f"{order['order_no']} · {order['vendor']} · {order['order_date']} · {status}"):
            lines = read(
                """SELECT b.item_name,b.spec,b.unit,b.tile_type AS stone_type,
                          ol.qty,ol.requested_delivery_date,ol.destination,
                          ol.delivery_recipient,ol.delivery_phone,ol.delivery_address
                   FROM order_lines ol JOIN budget_items b ON ol.item_id=b.id
                   WHERE ol.order_id=? ORDER BY ol.id""",
                (int(order["id"]),),
            )
            if len(lines):
                show = lines[["stone_type","item_name","spec","qty","unit","requested_delivery_date"]].copy()
                show.columns = ["석재구분","품명","규격","수량","단위","납품요청일"]
                st.dataframe(show, use_container_width=True, hide_index=True)
                first = lines.iloc[0]
                st.caption(f"납품구분: {first.get('destination','')} | 받는 사람: {first.get('delivery_recipient','')} | 연락처: {first.get('delivery_phone','')} | 주소: {first.get('delivery_address','')}")

            at = read("SELECT id,file_name,mime_type,file_size,file_data,created_at FROM order_attachments WHERE order_id=? ORDER BY id", (int(order["id"]),))
            if len(at):
                st.write(f"첨부파일 {len(at)}개")
                for _, a in at.iterrows():
                    raw = a["file_data"]
                    if hasattr(raw, "tobytes"):
                        raw = raw.tobytes()
                    elif isinstance(raw, memoryview):
                        raw = raw.tobytes()
                    elif not isinstance(raw, bytes):
                        raw = bytes(raw)
                    st.download_button(f"📎 {a['file_name']}", data=raw, file_name=a["file_name"], mime=str(a["mime_type"] or "application/octet-stream"), key=f"stone_attach_v4_{int(a['id'])}")
            else:
                st.caption("첨부된 도해도/파일이 없습니다.")

            if is_admin():
                st.markdown("#### 관리자 결재 / 발주 관리")
                s1, s2, s3 = st.columns(3)
                partner_confirm = s1.checkbox("협력사 확인", value=bool(order["partner_confirm"]), key=f"stone_partner_confirm_{int(order['id'])}")
                internal_approval = s2.checkbox("결재 완료", value=bool(order["internal_approval"]), key=f"stone_internal_approval_{int(order['id'])}")
                order_complete = s3.checkbox("발주 완료", value=bool(order["order_complete"]), key=f"stone_order_complete_{int(order['id'])}")
                c1, c2 = st.columns(2)
                if c1.button("상태 저장", key=f"stone_status_save_{int(order['id'])}", type="primary"):
                    execute("UPDATE orders SET partner_confirm=?,internal_approval=?,order_complete=? WHERE id=?", (int(partner_confirm),int(internal_approval),int(order_complete),int(order["id"])))
                    log_change("STATUS_UPDATE", "order", int(order["id"]), f"order_no={order['order_no']}")
                    st.success("발주서 상태를 저장했습니다.")
                    st.rerun()

                confirm_delete = c2.checkbox("삭제 확인", key=f"stone_delete_confirm_{int(order['id'])}")
                if c2.button("발주서 삭제(보관)", key=f"stone_delete_{int(order['id'])}"):
                    if not confirm_delete:
                        st.warning("삭제 확인을 먼저 체크해주세요.")
                    else:
                        oid = int(order["id"])
                        order_no = str(order["order_no"])
                        deleted_at = pd.Timestamp.now().isoformat()
                        execute("UPDATE orders SET deleted_at=?,deleted_by=? WHERE id=?", (deleted_at,"관리자",oid))
                        execute("UPDATE transactions SET deleted_at=?,deleted_by=? WHERE (order_id=? OR (tx_type='발주' AND note LIKE ?))", (deleted_at,"관리자",oid,f"%{order_no}%"))
                        log_change("SOFT_DELETE", "order", oid, f"order_no={order_no}")
                        st.success(f"{order_no} 발주서를 삭제 보관함으로 이동했습니다. 첨부/품목 데이터는 보존됩니다.")
                        st.rerun()
            else:
                st.caption("결재 상태 변경 및 발주서 삭제는 관리자만 가능합니다.")
'''
    source = source[:recent_start] + recent_block

source = source.replace('UnicodeCIDFont("HYSMyeongJo-Medium")', 'UnicodeCIDFont("HYSMyeongJoStd-Medium")')
source = source.replace('st.caption("☁ 중앙 DB 연결")', 'st.caption("☁ 중앙 DB 연결 · 석재 데이터 영구저장")', 1)

exec(compile(source, str(SRC), "exec"), globals(), globals())
