import io
import os
import sqlite3
from pathlib import Path
from datetime import date

import pandas as pd
import psycopg2
import streamlit as st

DB = Path("material_manager_v11.db")
CATEGORY = "석재"
STONE_TYPES = ["인조석", "천연가공석"]


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
    with sqlite3.connect(DB) as c:
        return pd.read_sql_query(sql, c, params=params)


def init_stone_db():
    delivery_columns = [
        ("delivery_recipient", "TEXT DEFAULT ''"),
        ("delivery_phone", "TEXT DEFAULT ''"),
        ("delivery_address", "TEXT DEFAULT ''"),
    ]

    if USE_POSTGRES:
        with psycopg2.connect(DATABASE_URL) as c:
            with c.cursor() as cur:
                for name, definition in delivery_columns:
                    cur.execute(
                        f"ALTER TABLE order_lines ADD COLUMN IF NOT EXISTS {name} {definition}"
                    )
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
            c.commit()
    else:
        with sqlite3.connect(DB) as c:
            existing = {row[1] for row in c.execute("PRAGMA table_info(order_lines)").fetchall()}
            for name, definition in delivery_columns:
                if name not in existing:
                    c.execute(f"ALTER TABLE order_lines ADD COLUMN {name} {definition}")
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
            c.commit()


init_stone_db()


def is_admin():
    return bool(st.session_state.get("is_admin", False))


def get_stone_items():
    return read(
        """SELECT id, category, vendor, item_name, spec, unit, budget_qty,
                  tile_type AS stone_type, default_destination, active
           FROM budget_items
           WHERE category=? AND active=1
           ORDER BY vendor, tile_type, item_name, spec""",
        (CATEGORY,),
    )


def get_stone_totals():
    return read(
        """SELECT b.id,b.vendor,b.item_name,b.spec,b.unit,b.budget_qty,
                  b.tile_type AS stone_type,b.default_destination,
                  COALESCE(SUM(CASE WHEN t.tx_type='발주' THEN t.qty ELSE 0 END),0) AS ordered,
                  COALESCE(SUM(CASE WHEN t.tx_type='입고' THEN t.qty ELSE 0 END),0) AS received,
                  COALESCE(SUM(CASE WHEN t.tx_type='투입' THEN t.qty ELSE 0 END),0) AS used
           FROM budget_items b
           LEFT JOIN transactions t ON b.id=t.item_id
           WHERE b.category=? AND b.active=1
           GROUP BY b.id
           ORDER BY b.vendor,b.tile_type,b.item_name,b.spec""",
        (CATEGORY,),
    )


def order_no_for(order_date):
    order_date_str = order_date.strftime("%Y%m%d")
    existing = read("SELECT order_no FROM orders WHERE order_no LIKE ?", (f"{order_date_str}-%",))
    numbers = []
    for value in existing["order_no"] if len(existing) else []:
        try:
            numbers.append(int(str(value).split("-")[-1]))
        except Exception:
            pass
    seq = max(numbers) + 1 if numbers else 1
    return f"{order_date_str}-{seq:03d}"


def save_attachments(order_id, files):
    for uploaded in files or []:
        data = uploaded.getvalue()
        execute(
            """INSERT INTO order_attachments(order_id,file_name,mime_type,file_size,file_data,created_at)
               VALUES(?,?,?,?,?,?)""",
            (int(order_id), str(uploaded.name), str(uploaded.type or ""), len(data), data, str(pd.Timestamp.now())),
        )


def get_attachments(order_id):
    return read(
        """SELECT id,file_name,mime_type,file_size,file_data,created_at
           FROM order_attachments WHERE order_id=? ORDER BY id""",
        (int(order_id),),
    )


def make_stone_pdf(order_row, lines):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont

    try:
        pdfmetrics.registerFont(UnicodeCIDFont("HYSMyeongJoStd-Medium"))
        font = "HYSMyeongJoStd-Medium"
    except Exception:
        font = "Helvetica"

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, rightMargin=28, leftMargin=28, topMargin=28, bottomMargin=28)
    styles = getSampleStyleSheet()
    normal = ParagraphStyle("stoneNormal", parent=styles["Normal"], fontName=font, fontSize=8.5, leading=11, alignment=1)
    title = ParagraphStyle("stoneTitle", parent=styles["Title"], fontName=font, fontSize=19, leading=23, alignment=1)
    label = ParagraphStyle("stoneLabel", parent=normal, textColor=colors.white)
    story = [Paragraph("석 재 발 주 서", title), Spacer(1, 8)]

    info = [
        [Paragraph("발주번호", label), Paragraph(str(order_row["order_no"]), normal), Paragraph("발주일", label), Paragraph(str(order_row["order_date"]), normal)],
        [Paragraph("협력사", label), Paragraph(str(order_row["vendor"]), normal), Paragraph("자재군", label), Paragraph(CATEGORY, normal)],
    ]
    table = Table(info, colWidths=[62,164,62,230])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (0,-1), colors.HexColor("#153A5B")),
        ("BACKGROUND", (2,0), (2,-1), colors.HexColor("#153A5B")),
        ("TEXTCOLOR", (0,0), (0,-1), colors.white),
        ("TEXTCOLOR", (2,0), (2,-1), colors.white),
        ("ALIGN", (0,0), (-1,-1), "CENTER"),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("GRID", (0,0), (-1,-1), 0.55, colors.HexColor("#9AA7B2")),
    ]))
    story += [table, Spacer(1, 10)]

    if len(lines):
        first = lines.iloc[0]
        delivery = [
            [Paragraph("납품구분", label), Paragraph(str(first.get("destination", "") or ""), normal), Paragraph("받는 사람", label), Paragraph(str(first.get("delivery_recipient", "") or ""), normal)],
            [Paragraph("연락처", label), Paragraph(str(first.get("delivery_phone", "") or ""), normal), Paragraph("납품주소", label), Paragraph(str(first.get("delivery_address", "") or ""), normal)],
        ]
        dt = Table(delivery, colWidths=[62,164,62,230])
        dt.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (0,-1), colors.HexColor("#153A5B")),
            ("BACKGROUND", (2,0), (2,-1), colors.HexColor("#153A5B")),
            ("TEXTCOLOR", (0,0), (0,-1), colors.white),
            ("TEXTCOLOR", (2,0), (2,-1), colors.white),
            ("ALIGN", (0,0), (-1,-1), "CENTER"),
            ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
            ("GRID", (0,0), (-1,-1), 0.55, colors.HexColor("#9AA7B2")),
        ]))
        story += [dt, Spacer(1, 10)]

    data = [[Paragraph("No.", label), Paragraph("석재구분", label), Paragraph("품명", label), Paragraph("규격", label), Paragraph("수량", label), Paragraph("단위", label), Paragraph("납품요청일", label)]]
    for i, r in lines.reset_index(drop=True).iterrows():
        data.append([
            Paragraph(str(i+1), normal), Paragraph(str(r.get("stone_type", "")), normal), Paragraph(str(r.get("item_name", "")), normal),
            Paragraph(str(r.get("spec", "")), normal), Paragraph(f"{float(r['qty']):,.2f}".rstrip("0").rstrip("."), normal),
            Paragraph(str(r.get("unit", "")), normal), Paragraph(str(r.get("requested_delivery_date", "")), normal),
        ])
    lt = Table(data, colWidths=[27,72,110,75,55,45,124], repeatRows=1)
    lt.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#153A5B")),
        ("TEXTCOLOR", (0,0), (-1,0), colors.white),
        ("ALIGN", (0,0), (-1,-1), "CENTER"),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("GRID", (0,0), (-1,-1), 0.5, colors.HexColor("#A9A9A9")),
    ]))
    story += [lt, Spacer(1, 12)]

    note = str(order_row.get("note", "") or "")
    if note:
        nt = Table([[Paragraph("비고", label), Paragraph(note, normal)]], colWidths=[62,456])
        nt.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (0,0), colors.HexColor("#153A5B")),
            ("TEXTCOLOR", (0,0), (0,0), colors.white),
            ("ALIGN", (0,0), (-1,-1), "CENTER"),
            ("GRID", (0,0), (-1,-1), 0.5, colors.HexColor("#A9A9A9")),
        ]))
        story += [nt]

    doc.build(story)
    return buf.getvalue()


st.title("석재 관리")
st.caption("인조석 + 천연가공석을 하나의 자재군으로 관리합니다.")

if is_admin():
    st.success("관리자 모드")
else:
    st.caption("일반 사용자는 투입내역 입력과 발주서 작성을 할 수 있습니다.")

df = get_stone_totals()

if len(df):
    show = df[["vendor","stone_type","item_name","spec","unit","budget_qty","ordered","received","used"]].copy()
    show["재고"] = show["received"] - show["used"]
    show["잔여예산"] = show["budget_qty"] - show["used"]
    show.columns = ["협력사","석재구분","품명","규격","단위","예산","누적발주","누적입고","누적투입","현재재고","잔여예산"]
    st.dataframe(show, use_container_width=True, hide_index=True)
else:
    st.info("등록된 석재 품목이 없습니다. 관리자 모드에서 인조석/천연가공석 품목을 등록하세요.")

if len(df):
    st.markdown("### 투입내역 입력")
    use = df[["id","vendor","stone_type","item_name","spec","unit","budget_qty","received","used"]].copy()
    use["이번 투입"] = 0.0
    use.columns = ["id","협력사","석재구분","품명","규격","단위","예산","누적입고","누적투입","이번 투입"]
    edit = st.data_editor(
        use, use_container_width=True, hide_index=True,
        disabled=["id","협력사","석재구분","품명","규격","단위","예산","누적입고","누적투입"],
        column_config={"id": None, "이번 투입": st.column_config.NumberColumn(min_value=0.0, step=0.1)},
        key="stone_use_editor",
    )
    u1, u2 = st.columns(2)
    use_date = u1.date_input("투입일", date.today(), key="stone_use_date")
    input_user = u2.text_input("입력자", key="stone_input_user")
    if st.button("석재 투입 저장", type="primary"):
        count = 0
        for _, r in edit.iterrows():
            q = float(r["이번 투입"] or 0)
            if q > 0:
                execute("""INSERT INTO transactions(tx_date,item_id,tx_type,qty,destination,note,input_user)
                           VALUES(?,?,?,?,?,?,?)""",
                        (str(use_date), int(r["id"]), "투입", q, "", "석재 투입", input_user))
                count += 1
        if count:
            st.success(f"{count}개 품목 투입내역 저장 완료")
            st.rerun()
        else:
            st.warning("투입수량을 입력하세요.")

if is_admin():
    st.markdown("---")
    st.markdown("### 석재 품목 관리")
    items = get_stone_items()
    edit_items = items[["id","vendor","stone_type","item_name","spec","unit","budget_qty","default_destination"]].copy()
    edit_items.columns = ["id","협력사","석재구분","품명","규격","단위","예산수량","기본납품처"]
    edited = st.data_editor(
        edit_items, use_container_width=True, hide_index=True, disabled=["id"], num_rows="dynamic",
        column_config={
            "id": None,
            "협력사": st.column_config.TextColumn(),
            "석재구분": st.column_config.SelectboxColumn(options=STONE_TYPES),
            "품명": st.column_config.TextColumn(),
            "규격": st.column_config.TextColumn(),
            "단위": st.column_config.TextColumn(),
            "예산수량": st.column_config.NumberColumn(min_value=0.0),
            "기본납품처": st.column_config.TextColumn(),
        }, key="stone_item_editor",
    )
    if st.button("석재 품목 저장", type="primary"):
        current_ids = set(items.id.astype(int).tolist()) if len(items) else set()
        edited_ids = set()
        for _, r in edited.iterrows():
            rid = r.get("id")
            vendor = str(r.get("협력사", "") or "").strip()
            stone_type = str(r.get("석재구분", "") or "").strip()
            item_name = str(r.get("품명", "") or "").strip()
            spec = str(r.get("규격", "") or "").strip()
            unit = str(r.get("단위", "") or "").strip()
            budget_qty = float(r.get("예산수량", 0) or 0)
            destination = str(r.get("기본납품처", "") or "").strip()
            if not stone_type or stone_type not in STONE_TYPES or not item_name or not unit:
                continue
            if pd.notna(rid):
                rid = int(rid)
                edited_ids.add(rid)
                execute("""UPDATE budget_items
                           SET vendor=?, item_name=?, spec=?, unit=?, budget_qty=?, tile_type=?, default_destination=?, active=1
                           WHERE id=? AND category=?""",
                        (vendor, item_name, spec, unit, budget_qty, stone_type, destination, rid, CATEGORY))
            else:
                execute("""INSERT INTO budget_items(
                            category,vendor,item_name,spec,unit,budget_qty,tile_type,application_type,default_destination,active)
                           VALUES(?,?,?,?,?,?,?,?,?,1)""",
                        (CATEGORY, vendor, item_name, spec, unit, budget_qty, stone_type, "", destination))
        for rid in current_ids - edited_ids:
            execute("UPDATE budget_items SET active=0 WHERE id=? AND category=?", (rid, CATEGORY))
        st.success("석재 품목 저장 완료")
        st.rerun()

st.markdown("---")
st.markdown("### 석재 발주")

vendors = [x for x in sorted(df.vendor.dropna().unique()) if str(x).strip()] if len(df) else []
if vendors:
    vendor = st.selectbox("협력사", vendors, key="stone_order_vendor")
    odf = df[df.vendor == vendor].copy()
    req = odf[["id","stone_type","item_name","spec","unit","budget_qty","ordered"]].copy()
    req.columns = ["id","석재구분","품명","규격","단위","예산","누적발주"]
    req["발주수량"] = 0.0
    req["납품요청일"] = date.today()
    req_edit = st.data_editor(
        req, use_container_width=True, hide_index=True,
        disabled=["id","석재구분","품명","규격","단위","예산","누적발주"],
        column_config={
            "id": None,
            "발주수량": st.column_config.NumberColumn(min_value=0.0, step=0.1),
            "납품요청일": st.column_config.DateColumn(format="YYYY-MM-DD"),
        }, key="stone_order_editor",
    )
    d1, d2 = st.columns(2)
    delivery_type = d1.selectbox("납품구분", ["현장", "기타"], key="stone_delivery_type")
    order_date = d2.date_input("발주일", date.today(), key="stone_order_date")
    recipient = st.text_input("받는 사람", key="stone_recipient")
    phone = st.text_input("연락처", key="stone_phone")
    address = st.text_input("납품 주소", key="stone_address")
    note = st.text_input("발주 비고", key="stone_order_note")

    st.markdown("#### 발주 건 첨부파일")
    st.caption("도해도, PDF, DWG, DXF 등 확장자 제한 없이 발주 1건에 여러 파일을 첨부할 수 있습니다.")
    attachments = st.file_uploader("첨부파일 선택", type=None, accept_multiple_files=True, key="stone_order_attachments")

    if st.button("석재 일괄 발주 + PDF 생성", type="primary", key="stone_order_save"):
        selected = req_edit[req_edit["발주수량"] > 0].copy()
        if not len(selected):
            st.warning("발주수량을 입력한 품목이 없습니다.")
        elif not recipient.strip():
            st.warning("받는 사람을 입력해주세요.")
        elif not phone.strip():
            st.warning("연락처를 입력해주세요.")
        elif not address.strip():
            st.warning("납품 주소를 입력해주세요.")
        else:
            order_no = order_no_for(order_date)
            execute("INSERT INTO orders(order_no,category,vendor,order_date,note) VALUES(?,?,?,?,?)",
                    (order_no, CATEGORY, vendor, str(order_date), note))
            oid = int(read("SELECT id FROM orders WHERE order_no=?", (order_no,)).iloc[0]["id"])
            for _, r in selected.iterrows():
                item_id = int(r["id"])
                qty = float(r["발주수량"])
                delivery_date = pd.to_datetime(r["납품요청일"]).date().isoformat()
                execute("""INSERT INTO order_lines(
                            order_id,item_id,qty,requested_delivery_date,destination,
                            delivery_recipient,delivery_phone,delivery_address)
                           VALUES(?,?,?,?,?,?,?,?)""",
                        (oid,item_id,qty,delivery_date,delivery_type,recipient.strip(),phone.strip(),address.strip()))
                execute("""INSERT INTO transactions(tx_date,item_id,tx_type,qty,destination,note,input_user)
                           VALUES(?,?,?,?,?,?,?)""",
                        (str(order_date),item_id,"발주",qty,delivery_type,f"발주서 {order_no}","일반사용자"))
            save_attachments(oid, attachments)
            lines = read("""SELECT b.item_name,b.spec,b.unit,b.tile_type AS stone_type,
                                 ol.qty,ol.destination,ol.requested_delivery_date,
                                 ol.delivery_recipient,ol.delivery_phone,ol.delivery_address
                          FROM order_lines ol JOIN budget_items b ON ol.item_id=b.id
                          WHERE ol.order_id=? ORDER BY ol.requested_delivery_date,ol.id""", (oid,))
            order_row = read("SELECT * FROM orders WHERE id=?", (oid,)).iloc[0]
            st.session_state["stone_last_pdf"] = make_stone_pdf(order_row, lines)
            st.session_state["stone_last_pdf_name"] = f"{order_no}_석재발주서.pdf"
            st.success(f"{len(selected)}개 품목 발주 완료 / 첨부 {len(attachments or [])}개")
            st.rerun()

    if st.session_state.get("stone_last_pdf"):
        st.download_button("📄 석재 발주서 PDF 다운로드", st.session_state["stone_last_pdf"], file_name=st.session_state["stone_last_pdf_name"], mime="application/pdf", key="stone_last_pdf_download")
else:
    st.info("먼저 관리자에서 석재 품목과 협력사를 등록하세요.")

st.markdown("---")
st.markdown("### 석재 발주 현황 / 첨부파일")
orders = read("SELECT * FROM orders WHERE category=? ORDER BY id DESC", (CATEGORY,))
if not len(orders):
    st.info("등록된 석재 발주가 없습니다.")
else:
    for _, order in orders.iterrows():
        with st.expander(f"{order['order_no']} | {order['vendor']} | {order['order_date']}"):
            lines = read("""SELECT b.item_name,b.spec,b.unit,b.tile_type AS stone_type,
                                 ol.qty,ol.destination,ol.requested_delivery_date
                          FROM order_lines ol JOIN budget_items b ON ol.item_id=b.id
                          WHERE ol.order_id=? ORDER BY ol.id""", (int(order.id),))
            st.dataframe(lines, use_container_width=True, hide_index=True)
            files = get_attachments(int(order.id))
            if len(files):
                st.write(f"**첨부파일 {len(files)}개**")
                for _, f in files.iterrows():
                    st.download_button(
                        f"📎 {f['file_name']} ({int(f['file_size']):,} bytes)",
                        bytes(f["file_data"]), file_name=str(f["file_name"]),
                        mime=str(f["mime_type"] or "application/octet-stream"), key=f"stone_attachment_{int(f['id'])}",
                    )
            else:
                st.caption("첨부파일 없음")
            pdf_lines = read("""SELECT b.item_name,b.spec,b.unit,b.tile_type AS stone_type,
                                      ol.qty,ol.destination,ol.requested_delivery_date,
                                      ol.delivery_recipient,ol.delivery_phone,ol.delivery_address
                               FROM order_lines ol JOIN budget_items b ON ol.item_id=b.id
                               WHERE ol.order_id=? ORDER BY ol.id""", (int(order.id),))
            st.download_button(
                "📄 이 발주서 PDF", make_stone_pdf(order, pdf_lines),
                file_name=f"{order['order_no']}_석재발주서.pdf", mime="application/pdf",
                key=f"stone_order_pdf_{int(order.id)}",
            )
