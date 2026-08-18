
import streamlit as st
import pandas as pd
import sqlite3
import os
import psycopg2
import hashlib
import io
import os
from pathlib import Path
from datetime import date, datetime
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.enums import TA_CENTER, TA_LEFT

SITE_NAME = "힐스테이트 레이크송도5차"
DB = Path("material_manager_v11.db")

# Cloud: Streamlit Secrets의 DATABASE_URL 사용
# Local: DATABASE_URL이 없으면 SQLite 파일 사용
def get_database_url():
    try:
        if "DATABASE_URL" in st.secrets:
            return str(st.secrets["DATABASE_URL"]).strip()
    except Exception:
        pass
    return os.environ.get("DATABASE_URL", "").strip()

DATABASE_URL = get_database_url()
USE_POSTGRES = bool(DATABASE_URL)

def _pg_sql(sql):
    # 기존 SQLite 스타일의 ? placeholder를 PostgreSQL %s로 변환
    return sql.replace("?", "%s")

def execute(sql, params=()):
    if USE_POSTGRES:
        with psycopg2.connect(DATABASE_URL) as c:
            with c.cursor() as cur:
                cur.execute(_pg_sql(sql), params)
            c.commit()
    else:
        with sqlite3.connect(DB) as c:
            c.execute(sql, params)
            c.commit()

def read(sql, params=()):
    if USE_POSTGRES:
        with psycopg2.connect(DATABASE_URL) as c:
            return pd.read_sql_query(_pg_sql(sql), c, params=params)
    else:
        with sqlite3.connect(DB) as c:
            return pd.read_sql_query(sql, c, params=params)

def sha(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def init_db():
    if USE_POSTGRES:
        ddl = [
            """CREATE TABLE IF NOT EXISTS settings(
                key TEXT PRIMARY KEY, value TEXT)""",
            """CREATE TABLE IF NOT EXISTS budget_items(
                id SERIAL PRIMARY KEY,
                category TEXT NOT NULL,
                vendor TEXT DEFAULT '',
                item_name TEXT NOT NULL,
                spec TEXT DEFAULT '',
                unit TEXT NOT NULL,
                budget_qty DOUBLE PRECISION DEFAULT 0,
                tile_type TEXT DEFAULT '',
                application_type TEXT DEFAULT '',
                default_destination TEXT DEFAULT '',
                active INTEGER DEFAULT 1
            )""",
            """CREATE TABLE IF NOT EXISTS transactions(
                id SERIAL PRIMARY KEY,
                tx_date TEXT NOT NULL,
                item_id INTEGER NOT NULL,
                tx_type TEXT NOT NULL,
                qty DOUBLE PRECISION NOT NULL,
                destination TEXT DEFAULT '',
                note TEXT DEFAULT '',
                input_user TEXT DEFAULT ''
            )""",
            """CREATE TABLE IF NOT EXISTS orders(
                id SERIAL PRIMARY KEY,
                order_no TEXT UNIQUE,
                category TEXT NOT NULL,
                vendor TEXT DEFAULT '',
                order_date TEXT NOT NULL,
                partner_confirm INTEGER DEFAULT 0,
                internal_approval INTEGER DEFAULT 0,
                order_complete INTEGER DEFAULT 0,
                note TEXT DEFAULT ''
            )""",
            """CREATE TABLE IF NOT EXISTS order_lines(
                id SERIAL PRIMARY KEY,
                order_id INTEGER NOT NULL,
                item_id INTEGER NOT NULL,
                qty DOUBLE PRECISION NOT NULL,
                requested_delivery_date TEXT DEFAULT '',
                destination TEXT DEFAULT ''
            )"""
        ]
        with psycopg2.connect(DATABASE_URL) as c:
            with c.cursor() as cur:
                for q in ddl:
                    cur.execute(q)
                cur.execute("SELECT value FROM settings WHERE key='admin_password'")
                if cur.fetchone() is None:
                    cur.execute("INSERT INTO settings(key,value) VALUES(%s,%s)", ("admin_password", sha("1234")))
            c.commit()
    else:
        with sqlite3.connect(DB) as c:
            c.execute("""CREATE TABLE IF NOT EXISTS settings(
                key TEXT PRIMARY KEY, value TEXT)""")
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
            if c.execute("SELECT value FROM settings WHERE key='admin_password'").fetchone() is None:
                c.execute("INSERT INTO settings(key,value) VALUES('admin_password',?)", (sha("1234"),))

def seed():
    n = int(read("SELECT COUNT(*) AS n FROM budget_items").iloc[0]["n"])
    if n == 0:
        rows = [
            ("철근","","철근","HD10","t",0,"","","",1),
            ("철근","","철근","HD13","t",0,"","","",1),
            ("철근","","철근","HD16","t",0,"","","",1),
            ("철근","","철근","HD19","t",0,"","","",1),
            ("철근","","철근","HD22","t",0,"","","",1),
            ("철근","","철근","HD25","t",0,"","","",1),
            ("레미콘","","레미콘","25-24-150","㎥",0,"","","",1),
            ("레미콘","","레미콘","25-27-150","㎥",0,"","","",1),
            ("타일","KCC타일","욕실 벽타일","","㎡",0,"욕실 벽타일","일반세대 시스템욕실","시스템욕실 공장",1),
            ("타일","KCC타일","욕실 바닥타일","","㎡",0,"욕실 바닥타일","일반세대 기타","현장",1),
            ("타일","대동타일","욕실 벽타일","","㎡",0,"욕실 벽타일","일반세대 시스템욕실","시스템욕실 공장",1),
            ("타일","대동타일","욕실 바닥타일","","㎡",0,"욕실 바닥타일","일반세대 기타","현장",1),
            ("타일","삼현타일","테라스 타일","","㎡",0,"테라스 타일","테라스하우스","현장",1),
            ("타일","세라믹타일","펜트하우스 타일","","㎡",0,"펜트하우스 타일","펜트하우스","현장",1),
        ]
        for r in rows:
            execute("""INSERT INTO budget_items(
                category,vendor,item_name,spec,unit,budget_qty,tile_type,
                application_type,default_destination,active)
                VALUES(?,?,?,?,?,?,?,?,?,?)""", r)

init_db()
# ---------------- 납품정보 DB 확장 ----------------
def migrate_delivery_columns():
    columns = [
        ("delivery_recipient", "TEXT DEFAULT ''"),
        ("delivery_phone", "TEXT DEFAULT ''"),
        ("delivery_address", "TEXT DEFAULT ''"),
    ]

    if USE_POSTGRES:
        with psycopg2.connect(DATABASE_URL) as c:
            with c.cursor() as cur:
                for name, definition in columns:
                    cur.execute(
                        f"ALTER TABLE order_lines ADD COLUMN IF NOT EXISTS {name} {definition}"
                    )
            c.commit()
    else:
        with sqlite3.connect(DB) as c:
            existing = {
                row[1]
                for row in c.execute("PRAGMA table_info(order_lines)").fetchall()
            }

            for name, definition in columns:
                if name not in existing:
                    c.execute(
                        f"ALTER TABLE order_lines ADD COLUMN {name} {definition}"
                    )

            c.commit()


migrate_delivery_columns()

seed()

# ---------------- helpers ----------------
def is_admin():
    return bool(st.session_state.get("is_admin", False))

def get_totals(category=None):
    where = "WHERE b.active=1"
    params = []
    if category:
        where += " AND b.category=?"
        params.append(category)
    q = f"""
    SELECT b.id,b.category,b.vendor,b.item_name,b.spec,b.unit,b.budget_qty,
           b.tile_type,b.application_type,b.default_destination,
           COALESCE(SUM(CASE WHEN t.tx_type='발주' THEN t.qty ELSE 0 END),0) AS ordered,
           COALESCE(SUM(CASE WHEN t.tx_type='입고' THEN t.qty ELSE 0 END),0) AS received,
           COALESCE(SUM(CASE WHEN t.tx_type='투입' THEN t.qty ELSE 0 END),0) AS used
    FROM budget_items b
    LEFT JOIN transactions t ON b.id=t.item_id
    {where}
    GROUP BY b.id
    ORDER BY b.category,b.vendor,b.spec,b.item_name
    """
    df = read(q, tuple(params))
    if len(df):
        df["재고"] = df["received"] - df["used"]
        df["잔여예산"] = df["budget_qty"] - df["used"]
    return df

def calc_destination(tile_type, application_type):
    if application_type == "일반세대 시스템욕실" and tile_type == "욕실 벽타일":
        return "시스템욕실 공장"
    return "현장"

def register_korean_font():
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont

    try:
        pdfmetrics.registerFont(
            UnicodeCIDFont("HYSMyeongJoStd-Medium")
        )
        return "HYSMyeongJoStd-Medium"
    except Exception:
        try:
            pdfmetrics.registerFont(
                UnicodeCIDFont("HYGothic-Medium")
            )
            return "HYGothic-Medium"
        except Exception:
            return "Helvetica"
PDF_FONT = register_korean_font()

def make_order_pdf(order_row, lines_df):
    buf = io.BytesIO()

    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        rightMargin=28,
        leftMargin=28,
        topMargin=28,
        bottomMargin=28
    )

    styles = getSampleStyleSheet()

    # ---------------- 기본 스타일 ----------------
    title = ParagraphStyle(
        "titleK",
        parent=styles["Title"],
        fontName=PDF_FONT,
        fontSize=19,
        leading=23,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#153A5B"),
        spaceAfter=8
    )

    normal = ParagraphStyle(
        "normalK",
        parent=styles["Normal"],
        fontName=PDF_FONT,
        fontSize=8.5,
        leading=11,
        alignment=TA_CENTER,
        textColor=colors.black
    )

    small = ParagraphStyle(
        "smallK",
        parent=normal,
        fontSize=7.7,
        leading=10,
        alignment=TA_CENTER
    )

    label = ParagraphStyle(
        "labelK",
        parent=normal,
        fontSize=8.5,
        leading=11,
        alignment=TA_CENTER,
        textColor=colors.white
    )

    story = []

    # ---------------- 제목 ----------------
    story.append(
        Paragraph("자 재 발 주 서", title)
    )

    story.append(
        Paragraph(
            SITE_NAME,
            ParagraphStyle(
                "siteK",
                parent=normal,
                fontSize=10.5,
                alignment=TA_CENTER,
                textColor=colors.HexColor("#5A6470"),
                spaceAfter=12
            )
        )
    )

    # ---------------- 발주 기본정보 ----------------
    info = [
        [
            Paragraph("<b>발주번호</b>", label),
            Paragraph(str(order_row["order_no"]), normal),
            Paragraph("<b>발주일</b>", label),
            Paragraph(str(order_row["order_date"]), normal)
        ],
        [
            Paragraph("<b>협력사</b>", label),
            Paragraph(str(order_row["vendor"]), normal),
            Paragraph("<b>현장명</b>", label),
            Paragraph(SITE_NAME, normal)
        ],
    ]

    info_table = Table(
        info,
        colWidths=[62, 164, 62, 230]
    )

    info_table.setStyle(
        TableStyle([
            ("FONTNAME", (0,0), (-1,-1), PDF_FONT),

            # 파란색 구분란 + 흰색 글씨
            ("BACKGROUND", (0,0), (0,-1), colors.HexColor("#153A5B")),
            ("BACKGROUND", (2,0), (2,-1), colors.HexColor("#153A5B")),
            ("TEXTCOLOR", (0,0), (0,-1), colors.white),
            ("TEXTCOLOR", (2,0), (2,-1), colors.white),

            # 전부 가운데 정렬
            ("ALIGN", (0,0), (-1,-1), "CENTER"),
            ("VALIGN", (0,0), (-1,-1), "MIDDLE"),

            ("GRID", (0,0), (-1,-1), 0.55, colors.HexColor("#9AA7B2")),

            ("LEFTPADDING", (0,0), (-1,-1), 6),
            ("RIGHTPADDING", (0,0), (-1,-1), 6),
            ("TOPPADDING", (0,0), (-1,-1), 6),
            ("BOTTOMPADDING", (0,0), (-1,-1), 6),
        ])
    )

    story += [
        info_table,
        Spacer(1, 10)
    ]

    # =========================================================
    # 납품 정보
    # =========================================================

    if len(lines_df):

        first = lines_df.iloc[0]

        delivery_destination = str(
            first.get("destination", "") or ""
        )

        delivery_recipient = str(
            first.get("delivery_recipient", "") or ""
        )

        delivery_phone = str(
            first.get("delivery_phone", "") or ""
        )

        delivery_address = str(
            first.get("delivery_address", "") or ""
        )

        delivery_info = [
            [
                Paragraph("<b>납품구분</b>", label),
                Paragraph(delivery_destination, normal),
                Paragraph("<b>받는 사람</b>", label),
                Paragraph(delivery_recipient, normal)
            ],
            [
                Paragraph("<b>연락처</b>", label),
                Paragraph(delivery_phone, normal),
                Paragraph("<b>납품 주소</b>", label),
                Paragraph(delivery_address, normal)
            ]
        ]

        delivery_table = Table(
            delivery_info,
            colWidths=[62, 164, 62, 230]
        )

        delivery_table.setStyle(
            TableStyle([
                ("FONTNAME", (0,0), (-1,-1), PDF_FONT),

                # 파란색 구분란
                ("BACKGROUND", (0,0), (0,-1), colors.HexColor("#153A5B")),
                ("BACKGROUND", (2,0), (2,-1), colors.HexColor("#153A5B")),

                # 구분란 글씨 흰색
                ("TEXTCOLOR", (0,0), (0,-1), colors.white),
                ("TEXTCOLOR", (2,0), (2,-1), colors.white),

                # 전부 가운데
                ("ALIGN", (0,0), (-1,-1), "CENTER"),
                ("VALIGN", (0,0), (-1,-1), "MIDDLE"),

                ("GRID", (0,0), (-1,-1), 0.55, colors.HexColor("#9AA7B2")),

                ("LEFTPADDING", (0,0), (-1,-1), 6),
                ("RIGHTPADDING", (0,0), (-1,-1), 6),
                ("TOPPADDING", (0,0), (-1,-1), 6),
                ("BOTTOMPADDING", (0,0), (-1,-1), 6),
            ])
        )

        story += [
            delivery_table,
            Spacer(1, 12)
        ]

    # ---------------- 품목 내역 ----------------
    line_data = [[
        Paragraph("<b>No.</b>", label),
        Paragraph("<b>품명</b>", label),
        Paragraph("<b>규격</b>", label),
        Paragraph("<b>수량</b>", label),
        Paragraph("<b>단위</b>", label),
        Paragraph("<b>납품처</b>", label),
        Paragraph("<b>납품요청일</b>", label),
    ]]

    for i, r in lines_df.reset_index(drop=True).iterrows():

        qty = float(r["qty"])

        line_data.append([
            Paragraph(str(i + 1), small),
            Paragraph(str(r["item_name"]), small),
            Paragraph(str(r["spec"] or ""), small),
            Paragraph(
                f"{qty:,.2f}".rstrip("0").rstrip("."),
                small
            ),
            Paragraph(str(r["unit"]), small),
            Paragraph(str(r["destination"]), small),
            Paragraph(str(r["requested_delivery_date"]), small),
        ])

    line_table = Table(
        line_data,
        colWidths=[27, 145, 70, 55, 40, 95, 86],
        repeatRows=1
    )

    line_table.setStyle(
        TableStyle([
            ("FONTNAME", (0,0), (-1,-1), PDF_FONT),

            # 헤더 파란색
            ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#153A5B")),

            # 헤더 흰색
            ("TEXTCOLOR", (0,0), (-1,0), colors.white),

            # 전체 가운데 정렬
            ("ALIGN", (0,0), (-1,-1), "CENTER"),
            ("VALIGN", (0,0), (-1,-1), "MIDDLE"),

            ("GRID", (0,0), (-1,-1), 0.5, colors.HexColor("#A9A9A9")),

            ("TOPPADDING", (0,0), (-1,-1), 5),
            ("BOTTOMPADDING", (0,0), (-1,-1), 5),
            ("LEFTPADDING", (0,0), (-1,-1), 4),
            ("RIGHTPADDING", (0,0), (-1,-1), 4),
        ])
    )

    story += [
        line_table,
        Spacer(1, 12)
    ]

    # ---------------- 비고 ----------------
    note = str(
        order_row.get("note", "") or ""
    )

    if note:
        note_table = Table(
            [[
                Paragraph("<b>비고</b>", label),
                Paragraph(note, normal)
            ]],
            colWidths=[62, 456]
        )

        note_table.setStyle(
            TableStyle([
                ("FONTNAME", (0,0), (-1,-1), PDF_FONT),
                ("BACKGROUND", (0,0), (0,0), colors.HexColor("#153A5B")),
                ("TEXTCOLOR", (0,0), (0,0), colors.white),
                ("ALIGN", (0,0), (-1,-1), "CENTER"),
                ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
                ("GRID", (0,0), (-1,-1), 0.5, colors.HexColor("#A9A9A9")),
                ("LEFTPADDING", (0,0), (-1,-1), 6),
                ("RIGHTPADDING", (0,0), (-1,-1), 6),
                ("TOPPADDING", (0,0), (-1,-1), 6),
                ("BOTTOMPADDING", (0,0), (-1,-1), 6),
            ])
        )

        story += [
            note_table,
            Spacer(1, 14)
        ]

    # ---------------- 결재란 ----------------
    approvals = [
        [
            Paragraph("<b>협력사</b>", label),
            Paragraph("<b>현대건설 담당</b>", label),
            Paragraph("<b>검토</b>", label),
            Paragraph("<b>승인</b>", label)
        ],
        ["", "", "", ""]
    ]

    approval_table = Table(
        approvals,
        colWidths=[129.5] * 4,
        rowHeights=[25, 45]
    )

    approval_table.setStyle(
        TableStyle([
            ("FONTNAME", (0,0), (-1,-1), PDF_FONT),

            ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#153A5B")),
            ("TEXTCOLOR", (0,0), (-1,0), colors.white),

            ("ALIGN", (0,0), (-1,-1), "CENTER"),
            ("VALIGN", (0,0), (-1,-1), "MIDDLE"),

            ("GRID", (0,0), (-1,-1), 0.65, colors.HexColor("#7F8C8D")),
        ])
    )

    story += [
        approval_table,
        Spacer(1, 9)
    ]

    story.append(
        Paragraph(
            "※ 품목별 지정 납품처 및 납품요청일을 준수하여 납품 바랍니다.",
            small
        )
    )

    doc.build(story)

    return buf.getvalue()
# ---------------- sidebar ----------------
st.sidebar.title("메뉴")
menu = st.sidebar.radio(
    "메뉴",
    ["한눈에 보기", "대시보드", "철근", "레미콘", "타일", "발주/결재 현황", "관리자 설정"],
    label_visibility="collapsed"
)
st.sidebar.markdown("---")    
if is_admin():
    st.sidebar.success("관리자 모드")
    if st.sidebar.button("관리자 로그아웃"):
        st.session_state["is_admin"] = False
        st.rerun()
else:
    st.sidebar.caption("일반 사용자: 투입내역 입력 가능")   
    with st.sidebar.expander("관리자 로그인"):
        pw = st.text_input("관리자 비밀번호", type="password")
        if st.button("로그인"):
            saved = read("SELECT value FROM settings WHERE key='admin_password'").iloc[0]["value"]
            if sha(pw) == saved:
                st.session_state["is_admin"] = True
                st.rerun()
            else:
                st.error("비밀번호가 맞지 않습니다.")

st.sidebar.caption("v1.1 · CLOUD")

col_logo, col_title = st.columns([1, 5])

with col_logo:
    st.image("202606220938554371_m.webp", width=85)

with col_title:
    st.title("Smart Material Manager")

st.caption(f"{SITE_NAME} · 철근 / 레미콘 / 타일 자재관리")
st.caption("☁ 중앙 DB 연결" if USE_POSTGRES else "💻 로컬 SQLite 모드")
# ---------------- pages ----------------
if menu == "한눈에 보기":
    st.subheader("한눈에 보기")
    totals = get_totals()
    orders = read("SELECT * FROM orders ORDER BY id DESC")
    today = date.today()

    c1,c2,c3,c4 = st.columns(4)
    c1.metric("등록 예산 품목", f"{len(totals)}종")
    c2.metric("철근 재고", f"{totals.loc[totals.category=='철근','재고'].sum():,.1f} t")
    c3.metric("발주 진행 건", f"{len(orders[orders.order_complete==0]) if len(orders) else 0}건")

    due7 = 0
    if len(orders):
        line_dates = read("""SELECT requested_delivery_date FROM order_lines ol
                             JOIN orders o ON ol.order_id=o.id WHERE o.order_complete=0""")
        for x in pd.to_datetime(line_dates.requested_delivery_date, errors="coerce"):
            if pd.notna(x) and 0 <= (x.date()-today).days <= 7:
                due7 += 1
    c4.metric("7일 이내 납품 품목", f"{due7}건")

    st.info("일반 사용자는 자재 투입수량을 입력할 수 있고, 예산/품목/입고/발주상태 수정은 관리자만 가능합니다.")

elif menu == "대시보드":
    st.subheader("대시보드")
    totals = get_totals()
    for cat in ["철근","레미콘","타일"]:
        st.markdown(f"### {cat}")
        d = totals[totals.category==cat].copy()
        if not len(d):
            st.write("등록 품목 없음")
            continue
        show = d[["vendor","item_name","spec","unit","budget_qty","ordered","received","used","재고","잔여예산"]].copy()
        show.columns = ["협력사","품명","규격","단위","예산","누적발주","누적입고","누적투입","현재재고","잔여예산"]
        if cat != "타일":
            show = show.drop(columns=["협력사"])
        st.dataframe(show, use_container_width=True, hide_index=True)

elif menu in ["철근","레미콘","타일"]:
    cat = menu
    st.subheader(f"{cat} 관리")
    df = get_totals(cat)

    if cat == "타일":
        disp = df[["id","vendor","item_name","spec","tile_type","application_type","default_destination","unit",
                   "budget_qty","ordered","received","used","재고"]].copy()
        disp.columns = ["id","협력사","품명","규격","타일구분","적용구분","납품처","단위",
                        "예산","누적발주","누적입고","누적투입","현재재고"]
    else:
        disp = df[["id","item_name","spec","unit","budget_qty","ordered","received","used","재고"]].copy()
        disp.columns = ["id","품명","규격","단위","예산","누적발주","누적입고","누적투입","현재재고"]

    st.dataframe(disp.drop(columns=["id"]), use_container_width=True, hide_index=True)

    st.markdown("### 투입내역 입력")
    st.caption("일반 사용자도 입력 가능합니다. 필요한 품목의 '이번 투입'만 적고 저장하세요.")
    use_df = disp.copy()
    use_df["이번 투입"] = 0.0
    disabled = [c for c in use_df.columns if c != "이번 투입"]
    use_edit = st.data_editor(
        use_df,
        use_container_width=True,
        hide_index=True,
        disabled=disabled,
        column_config={
            "id": None,
            "이번 투입": st.column_config.NumberColumn(min_value=0.0, step=0.1)
        },
        key=f"use_{cat}"
    )
    a,b = st.columns(2)
    use_date = a.date_input("투입일", date.today(), key=f"use_date_{cat}")
    input_user = b.text_input("입력자", key=f"user_{cat}", placeholder="예: 김OO")
    note = st.text_input("투입 비고", key=f"use_note_{cat}")
    if st.button(f"{cat} 투입 저장", type="primary", key=f"use_save_{cat}"):
        count = 0
        for _, r in use_edit.iterrows():
            q = float(r["이번 투입"] or 0)
            if q > 0:
                destination = r.get("납품처","") if cat=="타일" else ""
                execute("""INSERT INTO transactions(tx_date,item_id,tx_type,qty,destination,note,input_user)
                           VALUES(?,?,?,?,?,?,?)""",
                        (str(use_date),int(r["id"]),"투입",q,destination,note,input_user))
                count += 1
        if count:
            st.success(f"{count}개 품목 투입내역 저장 완료")
            st.rerun()
        else:
            st.warning("투입수량을 입력하세요.")

    if is_admin():
        st.markdown("---")
        st.markdown("### 관리자 입력 — 발주 / 입고")
        adm = disp.copy()
        adm["이번 발주"] = 0.0
        adm["이번 입고"] = 0.0
        disabled2 = [c for c in adm.columns if c not in ["이번 발주","이번 입고"]]
        adm_edit = st.data_editor(
            adm,
            use_container_width=True,
            hide_index=True,
            disabled=disabled2,
            column_config={
                "id": None,
                "이번 발주": st.column_config.NumberColumn(min_value=0.0, step=0.1),
                "이번 입고": st.column_config.NumberColumn(min_value=0.0, step=0.1),
            },
            key=f"adm_{cat}"
        )
        adm_date = st.date_input("발주/입고 기준일", date.today(), key=f"adm_date_{cat}")
        if st.button("관리자 발주/입고 저장", key=f"adm_save_{cat}"):
            count = 0
            for _, r in adm_edit.iterrows():
                destination = r.get("납품처","") if cat=="타일" else ""
                for col, typ in [("이번 발주","발주"),("이번 입고","입고")]:
                    q = float(r[col] or 0)
                    if q > 0:
                        execute("""INSERT INTO transactions(tx_date,item_id,tx_type,qty,destination,note,input_user)
                                   VALUES(?,?,?,?,?,?,?)""",
                                (str(adm_date),int(r["id"]),typ,q,destination,"관리자입력","관리자"))
                        count += 1
            st.success(f"{count}건 저장 완료")
            st.rerun()

    if cat == "타일":
        st.markdown("---")
        st.markdown("### 타일 발주서 작성")
        st.info("발주서 작성은 일반 사용자도 가능합니다. 예산/품목 수정, 입고 등록, 발주 상태 변경은 관리자만 가능합니다.")
        vendors = [x for x in sorted(df.vendor.dropna().unique()) if x]
        if vendors:
            vendor = st.selectbox("협력사", vendors)
            odf = df[df.vendor==vendor].copy()
            req = odf[["id","item_name","spec","tile_type","application_type",
                       "unit","budget_qty","ordered"]].copy()
            req.columns = ["id","품명","규격","타일구분","적용구분","단위","예산","누적발주"]
            req["발주수량"] = 0.0
            req["납품요청일"] = date.today()

        # ---------------- 납품 정보 ----------------
        st.markdown("### 납품 정보")

        delivery_type = st.radio(
            "납품구분",
            ["시스템욕실 공장", "현장"],
            horizontal=True,
            key="tile_delivery_type"
        )

        d1, d2 = st.columns(2)

        delivery_recipient = d1.text_input(
            "받는 사람",
            key="tile_delivery_recipient"
        )

        delivery_phone = d2.text_input(
            "연락처",
            key="tile_delivery_phone"
        )

        if delivery_type == "현장":
            site_df = read(
                "SELECT value FROM settings WHERE key='site_address'"
            )

            default_site_address = (
                str(site_df.iloc[0]["value"])
                if len(site_df)
                else ""
            )

            delivery_address = st.text_input(
                "현장 주소",
                value=default_site_address,
                key="tile_delivery_address_site"
            )

            st.caption(
                "현장 주소는 기본 현장 주소가 표시되며, 협력사가 납품 장소에 맞게 수정할 수 있습니다."
            )

        else:
            delivery_address = st.text_input(
                "시스템욕실 공장 주소",
                key="tile_factory_address"
            )
        st.caption(
            "같은 협력사 품목을 여러 개 한 번에 선택하고, "
            "각 품목별로 납품일을 다르게 지정할 수 있습니다."
        )

        st.markdown("---")
        # ---------------- 품목 선택 ----------------
        req_edit = st.data_editor(
            req,
            use_container_width=True,
            hide_index=True,
            disabled=[
                "품명",
                "규격",
                "타일구분",
                "적용구분",
                "단위",
                "예산",
                "누적발주"
            ],
            column_config={   
                                 "id": None,
                    "발주수량": st.column_config.NumberColumn(
                        min_value=0.0,
                        step=0.1
                    ),
                    "납품요청일": st.column_config.DateColumn(
                        format="YYYY-MM-DD"
                    ),
                },
                key="tile_multi_order"
            )

            # ---------------- 발주 기본정보 ----------------
        c1, c2 = st.columns(2)

        order_date = c1.date_input(
                "발주일",
                date.today(),
                key="multi_order_date"
            )

        order_note = c2.text_input(
                "발주 비고",
                key="multi_order_note"
            )

            # ---------------- 발주 + PDF ----------------
        if st.button(
                "선택 품목 일괄 발주 + PDF 생성",
                type="primary"
            ):
                selected = req_edit[
                    req_edit["발주수량"] > 0
                ].copy()

                if not len(selected):
                    st.warning("발주수량을 입력한 품목이 없습니다.")

                elif not delivery_recipient.strip():
                    st.warning("받는 사람을 입력해주세요.")

                elif not delivery_phone.strip():
                    st.warning("연락처를 입력해주세요.")

                elif not delivery_address.strip():
                    if delivery_type == "현장" and not is_admin():
                        st.warning("현장 주소는 시공사 관리자만 입력할 수 있습니다.")
                    else:
                        st.warning("주소를 입력해주세요.")

                else:
                    order_no = (
                        f"T-{order_date.strftime('%Y%m%d')}-"
                        f"{datetime.now().strftime('%H%M%S')}"
                    )

                    execute(
                        """INSERT INTO orders(
                            order_no,
                            category,
                            vendor,
                            order_date,
                            note
                        )
                        VALUES(?,?,?,?,?)""",
                        (
                            order_no,
                            "타일",
                            vendor,
                            str(order_date),
                            order_note
                        )
                    )

                    oid = int(
                        read(
                            "SELECT id FROM orders WHERE order_no=?",
                            (order_no,)
                        ).iloc[0]["id"]
                    )

                    # ---------------- 발주 품목 저장 ----------------
                    for _, r in selected.iterrows():

                        item_id = int(r["id"])
                        qty = float(r["발주수량"])

                        d = (
                            pd.to_datetime(
                                r["납품요청일"]
                            ).date().isoformat()
                        )

                        execute(
                            """INSERT INTO order_lines(
                                order_id,
                                item_id,
                                qty,
                                requested_delivery_date,
                                destination,
                                delivery_recipient,
                                delivery_phone,
                                delivery_address
                            )
                            VALUES(?,?,?,?,?,?,?,?)""",
                            (
                                oid,
                                item_id,
                                qty,
                                d,
                                delivery_type,
                                delivery_recipient.strip(),
                                delivery_phone.strip(),
                                delivery_address.strip()
                            )
                        )

                        execute(
                            """INSERT INTO transactions(
                                tx_date,
                                item_id,
                                tx_type,
                                qty,
                                destination,
                                note,
                                input_user
                            )
                            VALUES(?,?,?,?,?,?,?)""",
                            (
                                str(order_date),
                                item_id,
                                "발주",
                                qty,
                                delivery_type,
                                f"발주서 {order_no}",
                                st.session_state.get(
                                    "multi_order_writer",
                                    ""
                                ) or "일반사용자"
                            )
                        )

                    # ---------------- PDF용 데이터 ----------------
                    lines = read(
                        """
                        SELECT
                            b.item_name,
                            b.spec,
                            b.unit,
                            ol.qty,
                            ol.destination,
                            ol.requested_delivery_date,
                            ol.delivery_recipient,
                            ol.delivery_phone,
                            ol.delivery_address
                        FROM order_lines ol
                        JOIN budget_items b
                            ON ol.item_id=b.id
                        WHERE ol.order_id=?
                        ORDER BY
                            ol.requested_delivery_date,
                            ol.id
                        """,
                        (oid,)
                    )

                    order_row = read(
                        "SELECT * FROM orders WHERE id=?",
                        (oid,)
                    ).iloc[0]

                    st.session_state["last_pdf"] = make_order_pdf(
                        order_row,
                        lines
                    )

                    st.session_state["last_pdf_name"] = (
                        f"{order_no}_발주서.pdf"
                    )

                    st.success(
                        f"{len(selected)}개 품목이 한 장의 발주서로 생성되었습니다."
                    )

            # ---------------- PDF 다운로드 ----------------
        if st.session_state.get("last_pdf"):
            st.download_button(
                "📄 일괄 발주서 PDF 다운로드",
                st.session_state["last_pdf"],
                file_name=st.session_state["last_pdf_name"],
                mime="application/pdf",
                type="primary"
                )
elif menu == "발주/결재 현황":
    st.subheader("발주 / 결재 현황")
    orders = read("SELECT * FROM orders ORDER BY id DESC")
    if not len(orders):
        st.write("등록된 발주가 없습니다.")
    else:
        today = date.today()
        for _, r in orders.iterrows():
            lines = read("""
                SELECT b.item_name,b.spec,b.unit,ol.qty,ol.destination,ol.requested_delivery_date
                FROM order_lines ol JOIN budget_items b ON ol.item_id=b.id
                WHERE ol.order_id=? ORDER BY ol.requested_delivery_date,ol.id
            """,(int(r.id),))
            nearest = ""
            if len(lines):
                ds = pd.to_datetime(lines.requested_delivery_date, errors="coerce").dropna()
                if len(ds):
                    days = (ds.min().date()-today).days
                    nearest = f"D-{days}" if days >= 0 else f"D+{abs(days)}"
            status = (
                "발주완료" if r.order_complete else
                "내부결재 완료" if r.internal_approval else
                "협력사 확인완료" if r.partner_confirm else "결재/확인중"
            )
            with st.expander(f"{r.order_no} | {r.vendor} | {status} | 최근 납품 {nearest}"):
                st.dataframe(
                    lines.rename(columns={
                        "item_name":"품명","spec":"규격","qty":"수량","unit":"단위",
                        "destination":"납품처","requested_delivery_date":"납품요청일"
                    }),
                    use_container_width=True, hide_index=True
                )
                if is_admin():
                    p1 = st.checkbox("협력사 확인", value=bool(r.partner_confirm), key=f"p{r.id}")
                    p2 = st.checkbox("내부 결재 완료", value=bool(r.internal_approval), key=f"a{r.id}")
                    p3 = st.checkbox("발주 완료", value=bool(r.order_complete), key=f"o{r.id}")
                    if st.button("상태 저장", key=f"s{r.id}"):
                        execute("""UPDATE orders SET partner_confirm=?,internal_approval=?,order_complete=? WHERE id=?""",
                                (int(p1),int(p2),int(p3),int(r.id)))
                        st.success("상태 저장 완료")
                        st.rerun()
                else:
                    st.caption("발주 상태 수정은 관리자만 가능합니다.")

                pdf_bytes = make_order_pdf(r, lines)
                st.download_button(
                    "PDF 발주서 다운로드",
                    pdf_bytes,
                    file_name=f"{r.order_no}_발주서.pdf",
                    mime="application/pdf",
                    key=f"pdf_{r.id}"
                )

elif menu == "관리자 설정":
    st.subheader("관리자 설정")
    if not is_admin():
        st.warning("관리자 로그인 후 사용할 수 있습니다.")
    else:
        st.markdown("### 예산 / 품목 관리")
        items = read("SELECT * FROM budget_items WHERE active=1 ORDER BY category,vendor,spec,item_name")
        edit_cols = ["id","category","vendor","item_name","spec","unit","budget_qty",
                     "tile_type","application_type","default_destination"]
        edited = st.data_editor(
            items[edit_cols],
            use_container_width=True,
            hide_index=True,
            disabled=["id"],
            num_rows="dynamic",
            column_config={
                "id": None,
                "category": st.column_config.SelectboxColumn("공종", options=["철근","레미콘","타일"]),
                "vendor": st.column_config.TextColumn("협력사"),
                "item_name": st.column_config.TextColumn("품명"),
                "spec": st.column_config.TextColumn("규격"),
                "unit": st.column_config.TextColumn("단위"),
                "budget_qty": st.column_config.NumberColumn("예산수량", min_value=0.0),
                "tile_type": st.column_config.SelectboxColumn("타일구분",
                    options=["","욕실 벽타일","욕실 바닥타일","테라스 타일","펜트하우스 타일","기타"]),
                "application_type": st.column_config.SelectboxColumn("적용구분",
                    options=["","일반세대 시스템욕실","일반세대 기타","테라스하우스","펜트하우스"]),
                "default_destination": st.column_config.SelectboxColumn("기본납품처",
                    options=["","현장","시스템욕실 공장"])
            }
        )
        if st.button("예산 / 품목 저장", type="primary"):
            current_ids = set(items.id.astype(int).tolist())
            edited_ids = set()
            for _, r in edited.iterrows():
                rid = r.get("id")
                category = str(r.get("category","")).strip()
                item_name = str(r.get("item_name","")).strip()
                if not category or not item_name:
                    continue
                vendor = str(r.get("vendor","") or "")
                spec = str(r.get("spec","") or "")
                unit = str(r.get("unit","") or "")
                budget_qty = float(r.get("budget_qty",0) or 0)
                tile_type = str(r.get("tile_type","") or "")
                application_type = str(r.get("application_type","") or "")
                default_destination = str(r.get("default_destination","") or "")
                if category == "타일" and not default_destination:
                    default_destination = calc_destination(tile_type,application_type)

                if pd.notna(rid):
                    rid = int(rid)
                    edited_ids.add(rid)
                    execute("""UPDATE budget_items SET category=?,vendor=?,item_name=?,spec=?,unit=?,budget_qty=?,
                               tile_type=?,application_type=?,default_destination=? WHERE id=?""",
                            (category,vendor,item_name,spec,unit,budget_qty,tile_type,
                             application_type,default_destination,rid))
                else:
                    execute("""INSERT INTO budget_items(category,vendor,item_name,spec,unit,budget_qty,
                               tile_type,application_type,default_destination,active)
                               VALUES(?,?,?,?,?,?,?,?,?,1)""",
                            (category,vendor,item_name,spec,unit,budget_qty,tile_type,
                             application_type,default_destination))
            for rid in current_ids - edited_ids:
                execute("UPDATE budget_items SET active=0 WHERE id=?", (rid,))
            st.success("저장 완료")
            st.rerun()

        st.markdown("---")
        st.markdown("### 관리자 비밀번호 변경")
        p1 = st.text_input("새 비밀번호", type="password")
        p2 = st.text_input("새 비밀번호 확인", type="password")
        if st.button("비밀번호 변경"):
            if len(p1) < 4:
                st.warning("4자리 이상 입력하세요.")
            elif p1 != p2:
                st.warning("비밀번호가 서로 다릅니다.")
            else:
                execute("UPDATE settings SET value=? WHERE key='admin_password'", (sha(p1),))
                st.success("비밀번호 변경 완료")
