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
        value = st.secrets.get("DATABASE_URL", "")
        if value:
            return str(value).strip()
    except Exception:
        pass
    return str(os.environ.get("DATABASE_URL", "")).strip()


DATABASE_URL = get_database_url()
USE_POSTGRES = bool(DATABASE_URL)

if not USE_POSTGRES:
    st.error("중앙 DB에 연결되지 않았습니다. Streamlit Cloud의 DATABASE_URL을 확인해주세요.")
    st.stop()


def _pg_sql(sql):
    return sql.replace("?", "%s")


def execute(sql, params=()):
    with psycopg2.connect(DATABASE_URL) as c:
        with c.cursor() as cur:
            cur.execute(_pg_sql(sql), params)
        c.commit()


def read(sql, params=()):
    with psycopg2.connect(DATABASE_URL) as c:
        return pd.read_sql_query(_pg_sql(sql), c, params=params)


def ensure_schema():
    with psycopg2.connect(DATABASE_URL) as c:
        with c.cursor() as cur:
            for name, definition in [
                ("delivery_recipient", "TEXT DEFAULT ''"),
                ("delivery_phone", "TEXT DEFAULT ''"),
                ("delivery_address", "TEXT DEFAULT ''"),
            ]:
                cur.execute(f"ALTER TABLE order_lines ADD COLUMN IF NOT EXISTS {name} {definition}")
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS order_attachments(
                    id SERIAL PRIMARY KEY,
                    order_id INTEGER NOT NULL,
                    file_name TEXT NOT NULL,
                    mime_type TEXT DEFAULT '',
                    file_size BIGINT DEFAULT 0,
                    file_data BYTEA NOT NULL,
                    created_at TEXT DEFAULT ''
                )
                """
            )
        c.commit()


def seed_stone_items():
    n = int(read("SELECT COUNT(*) AS n FROM budget_items WHERE category=? AND active=1", (CATEGORY,)).iloc[0]["n"])
    if n:
        return
    for stone_type in STONE_TYPES:
        execute(
            """
            INSERT INTO budget_items(
                category,vendor,item_name,spec,unit,budget_qty,
                tile_type,application_type,default_destination,active
            ) VALUES(?,?,?,?,?,?,?,?,?,1)
            """,
            (CATEGORY, "", stone_type, "", "M", 100.0, stone_type, "", "현장"),
        )


ensure_schema()
seed_stone_items()


def is_admin():
    return bool(st.session_state.get("is_admin", False))


def stone_totals():
    return read(
        """
        SELECT
            b.id,b.vendor,b.item_name,b.spec,b.unit,b.budget_qty,
            b.tile_type AS stone_type,b.default_destination,
            COALESCE(SUM(CASE WHEN t.tx_type='발주' THEN t.qty ELSE 0 END),0) AS ordered,
            COALESCE(SUM(CASE WHEN t.tx_type='입고' THEN t.qty ELSE 0 END),0) AS received,
            COALESCE(SUM(CASE WHEN t.tx_type='투입' THEN t.qty ELSE 0 END),0) AS used
        FROM budget_items b
        LEFT JOIN transactions t ON b.id=t.item_id
        WHERE b.category=? AND b.active=1
        GROUP BY b.id
        ORDER BY b.vendor,b.tile_type,b.item_name,b.spec
        """,
        (CATEGORY,),
    )


def next_order_no(order_date):
    prefix = order_date.strftime("%Y%m%d")
    rows = read("SELECT order_no FROM orders WHERE category=? AND order_no LIKE ?", (CATEGORY, f"{prefix}-%"))
    nums = []
    for x in rows["order_no"] if len(rows) else []:
        try:
            nums.append(int(str(x).split("-")[-1]))
        except Exception:
            pass
    return f"{prefix}-{(max(nums) + 1 if nums else 1):03d}"


def save_attachments(order_id, files):
    for f in files or []:
        data = f.getvalue()
        execute(
            """
            INSERT INTO order_attachments(order_id,file_name,mime_type,file_size,file_data,created_at)
            VALUES(?,?,?,?,?,?)
            """,
            (int(order_id), str(f.name), str(f.type or ""), len(data), data, str(pd.Timestamp.now())),
        )


def make_pdf(order_row, lines):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont

    try:
        pdfmetrics.registerFont(UnicodeCIDFont("HYSMyeongJo-Medium"))
        font = "HYSMyeongJo-Medium"
    except Exception:
        font = "Helvetica"

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, rightMargin=28, leftMargin=28, topMargin=28, bottomMargin=28)
    styles = getSampleStyleSheet()
    normal = ParagraphStyle("normalK", parent=styles["Normal"], fontName=font, fontSize=8.5, leading=11, alignment=1)
    title = ParagraphStyle("titleK", parent=styles["Title"], fontName=font, fontSize=19, leading=23, alignment=1)
    label = ParagraphStyle("labelK", parent=normal, textColor=colors.white)

    story = [Paragraph("석 재 발 주 서", title), Spacer(1, 8)]
    info = [
        [Paragraph("발주번호", label), Paragraph(str(order_row["order_no"]), normal), Paragraph("발주일", label), Paragraph(str(order_row["order_date"]), normal)],
        [Paragraph("협력사", label), Paragraph(str(order_row["vendor"]), normal), Paragraph("자재군", label), Paragraph(CATEGORY, normal)],
    ]
    t = Table(info, colWidths=[62,164,62,230])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (0,-1), colors.HexColor("#153A5B")),
        ("BACKGROUND", (2,0), (2,-1), colors.HexColor("#153A5B")),
        ("TEXTCOLOR", (0,0), (0,-1), colors.white), ("TEXTCOLOR", (2,0), (2,-1), colors.white),
        ("ALIGN", (0,0), (-1,-1), "CENTER"), ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("GRID", (0,0), (-1,-1), 0.55, colors.HexColor("#9AA7B2")),
    ]))
    story += [t, Spacer(1,10)]

    if len(lines):
        first = lines.iloc[0]
        delivery = [
            [Paragraph("납품구분", label), Paragraph(str(first.get("destination", "") or ""), normal), Paragraph("받는 사람", label), Paragraph(str(first.get("delivery_recipient", "") or ""), normal)],
            [Paragraph("연락처", label), Paragraph(str(first.get("delivery_phone", "") or ""), normal), Paragraph("납품주소", label), Paragraph(str(first.get("delivery_address", "") or ""), normal)],
        ]
        dt = Table(delivery, colWidths=[62,164,62,230])
        dt.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (0,-1), colors.HexColor("#153A5B")), ("BACKGROUND", (2,0), (2,-1), colors.HexColor("#153A5B")),
            ("TEXTCOLOR", (0,0), (0,-1), colors.white), ("TEXTCOLOR", (2,0), (2,-1), colors.white),
            ("ALIGN", (0,0), (-1,-1), "CENTER"), ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
            ("GRID", (0,0), (-1,-1), 0.55, colors.HexColor("#9AA7B2")),
        ]))
        story += [dt, Spacer(1,10)]

    data = [[Paragraph("No.", label), Paragraph("석재구분", label), Paragraph("품명", label), Paragraph("규격", label), Paragraph("수량", label), Paragraph("단위", label), Paragraph("납품요청일", label)]]
    for i, r in lines.reset_index(drop=True).iterrows():
        qty = f"{float(r['qty']):,.2f}".rstrip("0").rstrip(".")
        data.append([Paragraph(str(i+1),normal), Paragraph(str(r.get("stone_type", "")),normal), Paragraph(str(r.get("item_name", "")),normal), Paragraph(str(r.get("spec", "")),normal), Paragraph(qty,normal), Paragraph(str(r.get("unit", "")),normal), Paragraph(str(r.get("requested_delivery_date", "")),normal)])
    lt = Table(data, colWidths=[27,72,110,75,55,45,124], repeatRows=1)
    lt.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#153A5B")), ("TEXTCOLOR", (0,0), (-1,0), colors.white),
        ("ALIGN", (0,0), (-1,-1), "CENTER"), ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("GRID", (0,0), (-1,-1), 0.5, colors.HexColor("#A9A9A9")),
    ]))
    story += [lt, Spacer(1,12)]
    if str(order_row.get("note", "") or ""):
        nt = Table([[Paragraph("비고", label), Paragraph(str(order_row["note"]), normal)]], colWidths=[62,456])
        nt.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (0,0), colors.HexColor("#153A5B")), ("TEXTCOLOR", (0,0), (0,0), colors.white),
            ("ALIGN", (0,0), (-1,-1), "CENTER"), ("GRID", (0,0), (-1,-1), 0.5, colors.HexColor("#A9A9A9")),
        ]))
        story.append(nt)
    doc.build(story)
    return buf.getvalue()


st.title("석재 관리")
st.caption("힐스테이트 레이크송도5차 · 인조석 / 천연가공석")
st.caption("☁ 중앙 DB 연결")

# --------------------------------------------------
# 관리자: 예산 / 품목 관리
# --------------------------------------------------
if is_admin():
    st.markdown("### 관리자 석재 예산 / 품목 관리")
    st.info("예산수량·규격·단위·석재구분은 관리자만 관리합니다. 신규 품목도 아래 폼에서 추가할 수 있습니다.")

    admin_df = stone_totals()
    edit = admin_df[["id","vendor","stone_type","item_name","spec","unit","budget_qty","default_destination"]].copy()
    edit.columns = ["id","협력사","석재구분","품명","규격","단위","예산수량","기본납품처"]

    with st.form("stone_admin_budget_form"):
        edited = st.data_editor(
            edit,
            use_container_width=True,
            hide_index=True,
            disabled=["id"],
            column_config={
                "id": None,
                "협력사": st.column_config.TextColumn("협력사"),
                "석재구분": st.column_config.SelectboxColumn("석재구분", options=STONE_TYPES),
                "품명": st.column_config.TextColumn("품명"),
                "규격": st.column_config.TextColumn("규격"),
                "단위": st.column_config.TextColumn("단위"),
                "예산수량": st.column_config.NumberColumn("예산수량", min_value=0.0, step=0.1),
                "기본납품처": st.column_config.TextColumn("기본납품처"),
            },
            key="stone_admin_editor",
        )
        save_budget = st.form_submit_button("예산 / 기존 품목 저장", type="primary")

    if save_budget:
        for _, r in edited.iterrows():
            rid = int(r["id"])
            execute(
                """
                UPDATE budget_items SET vendor=?,tile_type=?,item_name=?,spec=?,unit=?,budget_qty=?,default_destination=?
                WHERE id=? AND category=?
                """,
                (str(r["협력사"] or "").strip(), str(r["석재구분"] or "").strip(), str(r["품명"] or "").strip(), str(r["규격"] or "").strip(), str(r["단위"] or "").strip(), float(r["예산수량"] or 0), str(r["기본납품처"] or "").strip(), rid, CATEGORY),
            )
        st.success("석재 예산 / 기존 품목 저장 완료")
        st.rerun()

    with st.form("stone_admin_new_item_form", clear_on_submit=True):
        st.markdown("#### 신규 석재 품목 추가")
        a1, a2 = st.columns(2)
        new_type = a1.selectbox("석재구분", STONE_TYPES, key="stone_admin_new_type")
        new_vendor = a2.text_input("협력사", key="stone_admin_new_vendor")
        a3, a4 = st.columns(2)
        new_name = a3.text_input("품명", key="stone_admin_new_name")
        new_spec = a4.text_input("규격", key="stone_admin_new_spec")
        a5, a6, a7 = st.columns(3)
        new_unit = a5.text_input("단위", value="M", key="stone_admin_new_unit")
        new_qty = a6.number_input("예산수량", min_value=0.0, value=0.0, step=0.1, key="stone_admin_new_qty")
        new_dest = a7.text_input("기본납품처", value="현장", key="stone_admin_new_dest")
        add_new = st.form_submit_button("신규 석재 품목 추가", type="primary")

    if add_new:
        if not new_name.strip() or not new_unit.strip():
            st.warning("품명과 단위를 입력해주세요.")
        else:
            dup = read("SELECT id FROM budget_items WHERE category=? AND item_name=? AND spec=? AND active=1", (CATEGORY,new_name.strip(),new_spec.strip()))
            if len(dup):
                st.warning("같은 품명·규격의 석재가 이미 있습니다.")
            else:
                execute(
                    """
                    INSERT INTO budget_items(category,vendor,item_name,spec,unit,budget_qty,tile_type,application_type,default_destination,active)
                    VALUES(?,?,?,?,?,?,?,?,?,1)
                    """,
                    (CATEGORY,new_vendor.strip(),new_name.strip(),new_spec.strip(),new_unit.strip(),float(new_qty),new_type,"",new_dest.strip()),
                )
                st.success("신규 석재 품목이 중앙 DB에 추가되었습니다.")
                st.rerun()

st.markdown("---")
st.markdown("### 석재 현황")
df = stone_totals()
if len(df):
    show = df[["vendor","stone_type","item_name","spec","unit","budget_qty","ordered","received","used"]].copy()
    show["재고"] = show["received"] - show["used"]
    show["잔여예산"] = show["budget_qty"] - show["used"]
    show.columns = ["협력사","석재구분","품명","규격","단위","예산","누적발주","누적입고","누적투입","현재재고","잔여예산"]
    st.dataframe(show, use_container_width=True, hide_index=True)
else:
    st.info("등록된 석재 품목이 없습니다.")

# --------------------------------------------------
# 협력사 품목 등록: 폼 제출 전에는 아무것도 DB에 저장하지 않음
# --------------------------------------------------
st.markdown("### 협력사 석재 품목 등록")
st.info("협력사가 신규 품목 정보를 입력합니다. 입력 중에는 DB에 저장되지 않으며, 등록 버튼을 눌렀을 때만 저장됩니다.")
with st.form("stone_partner_register_form", clear_on_submit=True):
    r1, r2 = st.columns(2)
    vendor_input = r1.text_input("협력사명")
    stone_type_input = r2.selectbox("석재구분", STONE_TYPES)
    r3, r4 = st.columns(2)
    item_name_input = r3.text_input("품명")
    spec_input = r4.text_input("규격")
    r5, r6 = st.columns(2)
    unit_input = r5.text_input("단위", placeholder="㎡, M, EA 등")
    default_dest_input = r6.text_input("기본 납품처", value="현장")
    partner_register = st.form_submit_button("석재 품목 등록", type="primary")

if partner_register:
    if not vendor_input.strip() or not item_name_input.strip() or not unit_input.strip():
        st.warning("협력사명·품명·단위를 입력해주세요.")
    else:
        dup = read("SELECT id FROM budget_items WHERE category=? AND vendor=? AND item_name=? AND spec=? AND active=1", (CATEGORY,vendor_input.strip(),item_name_input.strip(),spec_input.strip()))
        if len(dup):
            st.warning("같은 협력사·품명·규격의 석재가 이미 등록되어 있습니다.")
        else:
            execute(
                """
                INSERT INTO budget_items(category,vendor,item_name,spec,unit,budget_qty,tile_type,application_type,default_destination,active)
                VALUES(?,?,?,?,?,?,?,?,?,1)
                """,
                (CATEGORY,vendor_input.strip(),item_name_input.strip(),spec_input.strip(),unit_input.strip(),0.0,stone_type_input,"",default_dest_input.strip()),
            )
            st.success("석재 품목이 중앙 DB에 등록되었습니다. 예산수량은 관리자가 설정합니다.")
            st.rerun()

# --------------------------------------------------
# 투입내역: 입력 중에는 저장하지 않고 '저장' 시에만 DB 반영
# --------------------------------------------------
if len(df):
    st.markdown("### 투입내역 입력")
    use = df[["id","vendor","stone_type","item_name","spec","unit","budget_qty","received","used"]].copy()
    use["이번 투입"] = 0.0
    use.columns = ["id","협력사","석재구분","품명","규격","단위","예산","누적입고","누적투입","이번 투입"]
    with st.form("stone_use_form"):
        edit_use = st.data_editor(
            use,
            use_container_width=True,
            hide_index=True,
            disabled=["id","협력사","석재구분","품명","규격","단위","예산","누적입고","누적투입"],
            column_config={"id": None, "이번 투입": st.column_config.NumberColumn(min_value=0.0, step=0.1)},
            key="stone_use_editor_v2",
        )
        u1, u2 = st.columns(2)
        use_date = u1.date_input("투입일", date.today())
        input_user = u2.text_input("입력자")
        save_use = st.form_submit_button("석재 투입 저장", type="primary")
    if save_use:
        count = 0
        for _, r in edit_use.iterrows():
            q = float(r["이번 투입"] or 0)
            if q > 0:
                execute("INSERT INTO transactions(tx_date,item_id,tx_type,qty,destination,note,input_user) VALUES(?,?,?,?,?,?,?)", (str(use_date),int(r["id"]),"투입",q,"","석재 투입",input_user.strip()))
                count += 1
        if count:
            st.success(f"{count}개 품목 투입내역 저장 완료")
            st.rerun()
        else:
            st.warning("투입수량을 입력하세요.")

# --------------------------------------------------
# 발주: 모든 입력을 하나의 폼에 넣어 타이핑 중 rerun 방지
# --------------------------------------------------
st.markdown("---")
st.markdown("### 석재 발주서 작성")
st.info("품목·납품정보·발주 비고·도해도를 모두 입력한 뒤 마지막 저장 버튼을 눌러주세요.")

vendors = [str(x) for x in sorted(df.vendor.dropna().unique()) if str(x).strip()] if len(df) else []
if vendors:
    with st.form("stone_order_form"):
        vendor = st.selectbox("협력사", vendors)
        odf = df[df.vendor == vendor].copy()
        req = odf[["id","item_name","spec","stone_type","unit","budget_qty","ordered"]].copy()
        req.columns = ["id","품명","규격","석재구분","단위","예산","누적발주"]
        req["발주수량"] = 0.0
        req["납품요청일"] = date.today()
        st.markdown("#### 품목 선택")
        req_edit = st.data_editor(
            req,
            use_container_width=True,
            hide_index=True,
            disabled=["id","품명","규격","석재구분","단위","예산","누적발주"],
            column_config={"id": None, "발주수량": st.column_config.NumberColumn(min_value=0.0, step=0.1), "납품요청일": st.column_config.DateColumn(format="YYYY-MM-DD")},
            key="stone_multi_order_v2",
        )
        st.markdown("#### 납품 정보")
        delivery_type = st.radio("납품구분", ["현장","기타"], horizontal=True)
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
        st.caption("도해도, PDF, DWG, DXF, 이미지 등을 여러 개 첨부할 수 있습니다.")
        attachments = st.file_uploader("도해도 및 첨부파일 선택", accept_multiple_files=True, key="stone_order_attachments_v2")
        save_order = st.form_submit_button("선택 품목 일괄 발주 + PDF 생성", type="primary")

    if save_order:
        selected = req_edit[req_edit["발주수량"] > 0].copy()
        if not len(selected):
            st.warning("발주수량을 입력한 품목이 없습니다.")
        elif not delivery_recipient.strip() or not delivery_phone.strip() or not delivery_address.strip():
            st.warning("받는 사람·연락처·납품 주소를 모두 입력해주세요.")
        else:
            order_no = next_order_no(order_date)
            execute("INSERT INTO orders(order_no,category,vendor,order_date,note) VALUES(?,?,?,?,?)", (order_no,CATEGORY,vendor,str(order_date),order_note.strip()))
            oid = int(read("SELECT id FROM orders WHERE order_no=?", (order_no,)).iloc[0]["id"])
            for _, r in selected.iterrows():
                item_id = int(r["id"])
                qty = float(r["발주수량"])
                delivery_date = pd.to_datetime(r["납품요청일"]).date().isoformat()
                execute(
                    """
                    INSERT INTO order_lines(order_id,item_id,qty,requested_delivery_date,destination,delivery_recipient,delivery_phone,delivery_address)
                    VALUES(?,?,?,?,?,?,?,?)
                    """,
                    (oid,item_id,qty,delivery_date,delivery_type,delivery_recipient.strip(),delivery_phone.strip(),delivery_address.strip()),
                )
                execute("INSERT INTO transactions(tx_date,item_id,tx_type,qty,destination,note,input_user) VALUES(?,?,?,?,?,?,?)", (str(order_date),item_id,"발주",qty,delivery_type,f"발주서 {order_no}",vendor))
            save_attachments(oid, attachments)
            lines = read(
                """
                SELECT b.item_name,b.spec,b.unit,b.tile_type AS stone_type,ol.qty,ol.destination,ol.requested_delivery_date,ol.delivery_recipient,ol.delivery_phone,ol.delivery_address
                FROM order_lines ol JOIN budget_items b ON ol.item_id=b.id WHERE ol.order_id=? ORDER BY ol.requested_delivery_date,ol.id
                """, (oid,)
            )
            order_row = read("SELECT * FROM orders WHERE id=?", (oid,)).iloc[0]
            st.session_state["stone_last_pdf"] = make_pdf(order_row, lines)
            st.session_state["stone_last_pdf_name"] = f"{order_no}_석재발주서.pdf"
            st.success(f"{len(selected)}개 품목 발주 완료 / 첨부 {len(attachments or [])}개")
            st.rerun()
else:
    st.info("등록된 협력사가 있는 석재 품목이 있어야 발주서를 작성할 수 있습니다.")

if st.session_state.get("stone_last_pdf"):
    st.download_button("📄 석재 발주서 PDF 다운로드", st.session_state["stone_last_pdf"], file_name=st.session_state["stone_last_pdf_name"], mime="application/pdf", type="primary", key="stone_pdf_download_v2")

st.markdown("---")
st.markdown("### 최근 석재 발주 / 도해도")
recent = read("SELECT id,order_no,vendor,order_date,note FROM orders WHERE category=? ORDER BY id DESC LIMIT 20", (CATEGORY,))
if not len(recent):
    st.info("등록된 석재 발주가 없습니다.")
else:
    for _, order in recent.iterrows():
        with st.expander(f"{order['order_no']} · {order['vendor']} · {order['order_date']}"):
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
                    st.download_button(f"📎 {a['file_name']}", data=raw, file_name=a["file_name"], mime=str(a["mime_type"] or "application/octet-stream"), key=f"stone_attach_v2_{int(a['id'])}")
            else:
                st.caption("첨부된 도해도/파일이 없습니다.")
