"""Stable stone entrypoint.
Uses the original feature-rich stone implementation with central-DB-first operation
and a safe SQLite fallback only when the central PostgreSQL DB is unavailable.
"""
from pathlib import Path

SRC = Path(__file__).with_name("stone_impl_v2.py")
source = SRC.read_text(encoding="utf-8")

# 1) Central DB first. Fall back to SQLite only if the configured PostgreSQL DB
# cannot be reached during startup.
start = source.index("DATABASE_URL = get_database_url()")
end = source.index("def seed_stone_items():")

stable_bootstrap = '''DATABASE_URL = get_database_url()
USE_POSTGRES = bool(DATABASE_URL)
CENTRAL_DB_ERROR = ""

if USE_POSTGRES:
    _probe = None
    try:
        _probe = psycopg2.connect(DATABASE_URL, connect_timeout=7)
        with _probe.cursor() as _cur:
            _cur.execute("SELECT 1")
    except Exception as _exc:
        CENTRAL_DB_ERROR = type(_exc).__name__
        USE_POSTGRES = False
    finally:
        if _probe is not None:
            try:
                _probe.close()
            except Exception:
                pass


def _pg_sql(sql):
    return sql.replace("?", "%s") if USE_POSTGRES else sql


def execute(sql, params=()):
    if USE_POSTGRES:
        with psycopg2.connect(DATABASE_URL, connect_timeout=7) as c:
            with c.cursor() as cur:
                cur.execute(_pg_sql(sql), params)
            c.commit()
    else:
        with sqlite3.connect(DB) as c:
            c.execute(sql, params)
            c.commit()


def read(sql, params=()):
    if USE_POSTGRES:
        with psycopg2.connect(DATABASE_URL, connect_timeout=7) as c:
            return pd.read_sql_query(_pg_sql(sql), c, params=params)
    with sqlite3.connect(DB) as c:
        return pd.read_sql_query(sql, c, params=params)


def ensure_schema():
    if USE_POSTGRES:
        ddl = [
            """CREATE TABLE IF NOT EXISTS budget_items(
                id SERIAL PRIMARY KEY, category TEXT NOT NULL, vendor TEXT DEFAULT '',
                item_name TEXT NOT NULL, spec TEXT DEFAULT '', unit TEXT NOT NULL,
                budget_qty DOUBLE PRECISION DEFAULT 0, tile_type TEXT DEFAULT '',
                application_type TEXT DEFAULT '', default_destination TEXT DEFAULT '',
                active INTEGER DEFAULT 1)""",
            """CREATE TABLE IF NOT EXISTS transactions(
                id SERIAL PRIMARY KEY, tx_date TEXT NOT NULL, item_id INTEGER NOT NULL,
                tx_type TEXT NOT NULL, qty DOUBLE PRECISION NOT NULL,
                destination TEXT DEFAULT '', note TEXT DEFAULT '', input_user TEXT DEFAULT '')""",
            """CREATE TABLE IF NOT EXISTS orders(
                id SERIAL PRIMARY KEY, order_no TEXT UNIQUE, category TEXT NOT NULL,
                vendor TEXT DEFAULT '', order_date TEXT NOT NULL,
                partner_confirm INTEGER DEFAULT 0, internal_approval INTEGER DEFAULT 0,
                order_complete INTEGER DEFAULT 0, note TEXT DEFAULT '')""",
            """CREATE TABLE IF NOT EXISTS order_lines(
                id SERIAL PRIMARY KEY, order_id INTEGER NOT NULL, item_id INTEGER NOT NULL,
                qty DOUBLE PRECISION NOT NULL, requested_delivery_date TEXT DEFAULT '',
                destination TEXT DEFAULT '')""",
            """CREATE TABLE IF NOT EXISTS order_attachments(
                id SERIAL PRIMARY KEY, order_id INTEGER NOT NULL,
                file_name TEXT NOT NULL, mime_type TEXT DEFAULT '', file_size INTEGER DEFAULT 0,
                file_data BYTEA NOT NULL, created_at TEXT DEFAULT '')""",
        ]
        with psycopg2.connect(DATABASE_URL, connect_timeout=7) as c:
            with c.cursor() as cur:
                for q in ddl:
                    cur.execute(q)
                for name in ["delivery_recipient", "delivery_phone", "delivery_address", "storage_location"]:
                    cur.execute(f"ALTER TABLE order_lines ADD COLUMN IF NOT EXISTS {name} TEXT DEFAULT ''")
            c.commit()
    else:
        with sqlite3.connect(DB) as c:
            c.execute("""CREATE TABLE IF NOT EXISTS budget_items(
                id INTEGER PRIMARY KEY AUTOINCREMENT, category TEXT NOT NULL, vendor TEXT DEFAULT '',
                item_name TEXT NOT NULL, spec TEXT DEFAULT '', unit TEXT NOT NULL,
                budget_qty REAL DEFAULT 0, tile_type TEXT DEFAULT '', application_type TEXT DEFAULT '',
                default_destination TEXT DEFAULT '', active INTEGER DEFAULT 1)""")
            c.execute("""CREATE TABLE IF NOT EXISTS transactions(
                id INTEGER PRIMARY KEY AUTOINCREMENT, tx_date TEXT NOT NULL, item_id INTEGER NOT NULL,
                tx_type TEXT NOT NULL, qty REAL NOT NULL, destination TEXT DEFAULT '',
                note TEXT DEFAULT '', input_user TEXT DEFAULT '')""")
            c.execute("""CREATE TABLE IF NOT EXISTS orders(
                id INTEGER PRIMARY KEY AUTOINCREMENT, order_no TEXT UNIQUE, category TEXT NOT NULL,
                vendor TEXT DEFAULT '', order_date TEXT NOT NULL, partner_confirm INTEGER DEFAULT 0,
                internal_approval INTEGER DEFAULT 0, order_complete INTEGER DEFAULT 0,
                note TEXT DEFAULT '')""")
            c.execute("""CREATE TABLE IF NOT EXISTS order_lines(
                id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL, item_id INTEGER NOT NULL,
                qty REAL NOT NULL, requested_delivery_date TEXT DEFAULT '', destination TEXT DEFAULT '')""")
            existing = {row[1] for row in c.execute("PRAGMA table_info(order_lines)").fetchall()}
            for name in ["delivery_recipient", "delivery_phone", "delivery_address", "storage_location"]:
                if name not in existing:
                    c.execute(f"ALTER TABLE order_lines ADD COLUMN {name} TEXT DEFAULT ''")
            c.execute("""CREATE TABLE IF NOT EXISTS order_attachments(
                id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL,
                file_name TEXT NOT NULL, mime_type TEXT DEFAULT '', file_size INTEGER DEFAULT 0,
                file_data BLOB NOT NULL, created_at TEXT DEFAULT '')""")
            c.commit()

'''
source = source[:start] + stable_bootstrap + source[end:]

# 2) Items/budget are managed only in the global 관리자 설정 screen.
admin_start_marker = '''# --------------------------------------------------
# 관리자: 예산 / 품목 관리
# --------------------------------------------------'''
admin_end_marker = 'st.markdown("---")\nst.markdown("### 석재 현황")'
a = source.find(admin_start_marker)
b = source.find(admin_end_marker)
if a >= 0 and b > a:
    source = source[:a] + source[b:]

# Remove the old partner item-registration form.
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

# 3) Replace the old vendor-dependent order block with a free-text vendor order form.
order_start = source.find('st.markdown("### 석재 발주서 작성")')
order_end = source.find('if st.session_state.get("stone_last_pdf"):', order_start)
order_block = r'''st.markdown("### 협력사 석재 발주서")
st.info("협력사명과 발주수량을 입력하고, 납품정보 및 도해도/첨부파일을 추가한 뒤 마지막 저장 버튼을 눌러주세요.")

if len(df):
    with st.form("stone_order_form_v3"):
        vendor = st.text_input("협력사명", placeholder="예: ○○석재")

        req = df[["id","item_name","spec","stone_type","unit","budget_qty","ordered"]].copy()
        req.columns = ["id","품명","규격","석재구분","단위","예산","누적발주"]
        req["발주수량"] = 0.0
        req["납품요청일"] = date.today()

        st.markdown("#### 품목 선택")
        req_edit = st.data_editor(
            req,
            use_container_width=True,
            hide_index=True,
            disabled=["id","품명","규격","석재구분","단위","예산","누적발주"],
            column_config={
                "id": None,
                "발주수량": st.column_config.NumberColumn("발주수량", min_value=0.0, step=0.1),
                "납품요청일": st.column_config.DateColumn("납품요청일", format="YYYY-MM-DD"),
            },
            key="stone_multi_order_v3",
        )

        st.markdown("#### 납품 정보")
        delivery_type = st.radio("납품구분", ["현장","기타"], horizontal=True, key="stone_delivery_type_v3")
        d1, d2 = st.columns(2)
        delivery_recipient = d1.text_input("받는 사람")
        delivery_phone = d2.text_input("연락처")

        site_address_df = read("SELECT value FROM settings WHERE key='site_address'")
        default_site_address = str(site_address_df.iloc[0]["value"]) if len(site_address_df) else ""
        if delivery_type == "현장":
            delivery_address = st.text_input("현장 주소", value=default_site_address)
        else:
            delivery_address = st.text_input("납품 주소")

        c1, c2 = st.columns(2)
        order_date = c1.date_input("발주일", date.today())
        order_note = c2.text_input("발주 비고")

        st.markdown("#### 도해도 / 첨부파일")
        st.caption("PDF, Excel(XLS/XLSX), CAD(DWG/DXF), 이미지 파일을 여러 개 동시에 첨부할 수 있습니다.")
        attachments = st.file_uploader(
            "도해도 및 첨부파일 선택",
            type=["pdf","xls","xlsx","dwg","dxf","png","jpg","jpeg","webp","bmp","tif","tiff"],
            accept_multiple_files=True,
            key="stone_order_attachments_v3",
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
                (order_no, CATEGORY, vendor.strip(), str(order_date), order_note.strip()),
            )
            oid = int(read("SELECT id FROM orders WHERE order_no=?", (order_no,)).iloc[0]["id"])

            for _, r in selected.iterrows():
                item_id = int(r["id"])
                qty = float(r["발주수량"])
                delivery_date = pd.to_datetime(r["납품요청일"]).date().isoformat()
                execute(
                    """INSERT INTO order_lines(
                           order_id,item_id,qty,requested_delivery_date,destination,
                           delivery_recipient,delivery_phone,delivery_address)
                       VALUES(?,?,?,?,?,?,?,?)""",
                    (oid,item_id,qty,delivery_date,delivery_type,delivery_recipient.strip(),delivery_phone.strip(),delivery_address.strip()),
                )
                execute(
                    "INSERT INTO transactions(tx_date,item_id,tx_type,qty,destination,note,input_user) VALUES(?,?,?,?,?,?,?)",
                    (str(order_date),item_id,"발주",qty,delivery_type,f"발주서 {order_no}",vendor.strip()),
                )

            save_attachments(oid, attachments)
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
            st.success(f"{len(selected)}개 품목 발주 완료 / 첨부 {len(attachments or [])}개")'''
if order_start >= 0 and order_end > order_start:
    source = source[:order_start] + order_block + "\n\n" + source[order_end:]

source = source.replace(
    'st.caption("☁ 중앙 DB 연결")',
    'st.caption("☁ 중앙 DB 연결" if USE_POSTGRES else "⚠ 중앙 DB 연결 실패 · 백업 DB")',
    1,
)
exec(compile(source, str(SRC), "exec"), globals(), globals())
