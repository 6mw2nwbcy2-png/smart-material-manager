"""Stable stone entrypoint.
Restores the original feature-rich stone order UI while keeping PostgreSQL calls out
of the deployed backup/stabilization runtime.
"""
from pathlib import Path

SRC = Path(__file__).with_name("stone_impl_v2.py")
source = SRC.read_text(encoding="utf-8")

# 1) Replace the PostgreSQL-only bootstrap with SQLite-compatible storage.
start = source.index("DATABASE_URL = get_database_url()")
end = source.index("def seed_stone_items():")

sqlite_bootstrap = '''DATABASE_URL = ""
USE_POSTGRES = False


def _pg_sql(sql):
    return sql


def execute(sql, params=()):
    with sqlite3.connect(DB) as c:
        c.execute(sql, params)
        c.commit()


def read(sql, params=()):
    with sqlite3.connect(DB) as c:
        return pd.read_sql_query(sql, c, params=params)


def ensure_schema():
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
        existing = {row[1] for row in c.execute("PRAGMA table_info(order_lines)").fetchall()}
        for name in ["delivery_recipient", "delivery_phone", "delivery_address", "storage_location"]:
            if name not in existing:
                c.execute(f"ALTER TABLE order_lines ADD COLUMN {name} TEXT DEFAULT ''")
        c.execute("""CREATE TABLE IF NOT EXISTS order_attachments(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            file_name TEXT NOT NULL,
            mime_type TEXT DEFAULT '',
            file_size INTEGER DEFAULT 0,
            file_data BLOB NOT NULL,
            created_at TEXT DEFAULT ''
        )""")
        c.commit()

'''

source = source[:start] + sqlite_bootstrap + source[end:]

# 2) Stone page should NOT contain separate admin budget/new-item forms.
admin_start_marker = '# --------------------------------------------------\n# 관리자: 예산 / 품목 관리\n# --------------------------------------------------'
admin_end_marker = 'st.markdown("---")\nst.markdown("### 석재 현황")'
a = source.find(admin_start_marker)
b = source.find(admin_end_marker)
if a >= 0 and b > a:
    source = source[:a] + source[b:]

# 3) Remove the old partner item-registration form entirely.
partner_start_marker = '# --------------------------------------------------\n# 협력사 품목 등록: 폼 제출 전에는 아무것도 DB에 저장하지 않음\n# --------------------------------------------------'
partner_end_marker = '# --------------------------------------------------\n# 투입내역: 입력 중에는 저장하지 않고 \'저장\' 시에만 DB 반영\n# --------------------------------------------------'
a = source.find(partner_start_marker)
b = source.find(partner_end_marker)
if a >= 0 and b > a:
    source = source[:a] + source[b:]

# 4) Rename the actual order form to the requested partner stone order form.
source = source.replace('st.markdown("### 석재 발주서 작성")', 'st.markdown("### 협력사 석재 발주서")', 1)
source = source.replace(
    'st.info("품목·납품정보·발주 비고·도해도를 모두 입력한 뒤 마지막 저장 버튼을 눌러주세요.")',
    'st.info("협력사·품목·납품정보·발주 비고·도해도/첨부파일을 모두 입력한 뒤 마지막 저장 버튼을 눌러주세요.")',
    1,
)
source = source.replace(
    'st.caption("도해도, PDF, DWG, DXF, 이미지 등을 여러 개 첨부할 수 있습니다.")',
    'st.caption("도해도와 PDF, Excel(XLS/XLSX), CAD(DWG/DXF), 이미지 등 여러 파일을 한 번에 첨부할 수 있습니다.")',
    1,
)
source = source.replace(
    'attachments = st.file_uploader("도해도 및 첨부파일 선택", accept_multiple_files=True, key="stone_order_attachments_v2")',
    'attachments = st.file_uploader("도해도 및 첨부파일 선택", type=["pdf","xls","xlsx","dwg","dxf","png","jpg","jpeg","webp","bmp","tif","tiff"], accept_multiple_files=True, key="stone_order_attachments_v2")',
    1,
)

source = source.replace('st.caption("☁ 중앙 DB 연결")', 'st.caption("🛡 안정화 모드 · 석재 발주 기능 복구")', 1)
exec(compile(source, str(SRC), "exec"), globals(), globals())
