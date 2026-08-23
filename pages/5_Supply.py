import streamlit as st
import pandas as pd
import sqlite3
import os
from pathlib import Path
from datetime import date, datetime

try:
    import psycopg2
except Exception:
    psycopg2 = None

st.set_page_config(page_title="지급자재 현황", layout="wide")

DB = Path("material_manager_v11.db")

def get_database_url():
    try:
        if "DATABASE_URL" in st.secrets:
            return str(st.secrets["DATABASE_URL"]).strip()
    except Exception:
        pass
    return os.environ.get("DATABASE_URL", "").strip()

DATABASE_URL = get_database_url()
USE_POSTGRES = bool(DATABASE_URL and psycopg2)

def pg_sql(sql):
    return sql.replace("?", "%s")

def execute(sql, params=()):
    if USE_POSTGRES:
        with psycopg2.connect(DATABASE_URL) as c:
            with c.cursor() as cur:
                cur.execute(pg_sql(sql), params)
            c.commit()
    else:
        with sqlite3.connect(DB) as c:
            c.execute(sql, params)
            c.commit()

def read(sql, params=()):
    if USE_POSTGRES:
        with psycopg2.connect(DATABASE_URL) as c:
            return pd.read_sql_query(pg_sql(sql), c, params=params)
    with sqlite3.connect(DB) as c:
        return pd.read_sql_query(sql, c, params=params)

# 기존 중앙 DB의 budget_items에 신규 관리 필드 추가
if USE_POSTGRES:
    with psycopg2.connect(DATABASE_URL) as c:
        with c.cursor() as cur:
            cur.execute("ALTER TABLE budget_items ADD COLUMN IF NOT EXISTS planned_delivery_date TEXT DEFAULT ''")
            cur.execute("ALTER TABLE budget_items ADD COLUMN IF NOT EXISTS storage_location TEXT DEFAULT ''")
            cur.execute("""CREATE TABLE IF NOT EXISTS material_documents(
                id SERIAL PRIMARY KEY,
                item_id INTEGER,
                file_name TEXT NOT NULL,
                upload_date TEXT NOT NULL,
                extracted_text TEXT DEFAULT '',
                applied_qty DOUBLE PRECISION DEFAULT 0,
                status TEXT DEFAULT '검토대기'
            )""")
        c.commit()
else:
    with sqlite3.connect(DB) as c:
        cols = {r[1] for r in c.execute("PRAGMA table_info(budget_items)").fetchall()}
        if "planned_delivery_date" not in cols:
            c.execute("ALTER TABLE budget_items ADD COLUMN planned_delivery_date TEXT DEFAULT ''")
        if "storage_location" not in cols:
            c.execute("ALTER TABLE budget_items ADD COLUMN storage_location TEXT DEFAULT ''")
        c.execute("""CREATE TABLE IF NOT EXISTS material_documents(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id INTEGER,
            file_name TEXT NOT NULL,
            upload_date TEXT NOT NULL,
            extracted_text TEXT DEFAULT '',
            applied_qty REAL DEFAULT 0,
            status TEXT DEFAULT '검토대기'
        )""")
        c.commit()

st.title("📦 지급자재 현황")
st.caption("지급자재 반입예정 · 현장입고 · 보관위치를 한 화면에서 관리합니다.")

items = read("""
SELECT b.id, b.category, b.vendor, b.item_name, b.spec, b.unit,
       b.budget_qty,
       COALESCE(SUM(CASE WHEN t.tx_type='발주' THEN t.qty ELSE 0 END),0) AS ordered,
       COALESCE(SUM(CASE WHEN t.tx_type='입고' THEN t.qty ELSE 0 END),0) AS received,
       COALESCE(SUM(CASE WHEN t.tx_type='투입' THEN t.qty ELSE 0 END),0) AS used,
       COALESCE(b.planned_delivery_date,'') AS planned_delivery_date,
       COALESCE(b.storage_location,'') AS storage_location
FROM budget_items b
LEFT JOIN transactions t ON b.id=t.item_id
WHERE b.active=1
GROUP BY b.id
ORDER BY b.category,b.vendor,b.spec,b.item_name
""")

if len(items):
    items["재고"] = items["received"] - items["used"]

    today = date.today()
    dates = pd.to_datetime(items["planned_delivery_date"], errors="coerce")
    due7 = int(((dates.notna()) & ((dates.dt.date - today).apply(lambda x: 0 <= x.days <= 7))).sum())
    overdue = int(((dates.notna()) & (dates.dt.date < today) & (items["received"] < items["ordered"])).sum())
    no_location = int((items["storage_location"].fillna("").str.strip() == "").sum())

    c1,c2,c3,c4 = st.columns(4)
    c1.metric("등록 자재", f"{len(items)}종")
    c2.metric("7일 이내 반입", f"{due7}건")
    c3.metric("반입 지연 의심", f"{overdue}건")
    c4.metric("보관위치 미등록", f"{no_location}건")

    st.markdown("### 📅 자재별 반입 / 재고 현황")
    show = items[["category","vendor","item_name","spec","unit","budget_qty","ordered","received","used","재고","planned_delivery_date","storage_location"]].copy()
    show.columns = ["공종","협력사","품명","규격","단위","예산","누적발주","누적입고","누적투입","현재재고","현장반입 예정일","보관위치"]
    st.dataframe(show, use_container_width=True, hide_index=True)

    st.markdown("### ✏️ 반입일정 / 보관위치 입력")
    edit = items[["id","category","vendor","item_name","spec","planned_delivery_date","storage_location"]].copy()
    edit.columns = ["id","공종","협력사","품명","규격","현장반입 예정일","보관위치"]
    edit["현장반입 예정일"] = pd.to_datetime(edit["현장반입 예정일"], errors="coerce")
    edit["현장반입 예정일"] = edit["현장반입 예정일"].dt.date

    with st.form("supply_schedule_form"):
        edited = st.data_editor(
            edit,
            use_container_width=True,
            hide_index=True,
            disabled=["id","공종","협력사","품명","규격"],
            column_config={
                "id": None,
                "현장반입 예정일": st.column_config.DateColumn("현장반입 예정일", format="YYYY-MM-DD"),
                "보관위치": st.column_config.TextColumn("보관위치", help="예: 지하주차장 B2 A구역"),
            },
            key="supply_schedule_editor",
        )
        save = st.form_submit_button("반입일정 / 보관위치 저장", type="primary")

    if save:
        for _, r in edited.iterrows():
            rid = int(r["id"])
            d = r["현장반입 예정일"]
            d = "" if pd.isna(d) else str(d)
            loc = str(r["보관위치"] or "").strip()
            execute("UPDATE budget_items SET planned_delivery_date=?, storage_location=? WHERE id=?", (d, loc, rid))
        st.success("반입일정과 보관위치를 저장했습니다.")
        st.rerun()
else:
    st.info("등록된 자재 품목이 없습니다.")

st.markdown("---")
st.markdown("### 📄 자재인수인계서 업로드")
st.caption("1차 버전은 인수인계서를 업로드하고 검토대기 상태로 보관합니다. 수량 자동반영은 문서 양식별 인식 규칙을 확정한 뒤 적용합니다.")

uploaded = st.file_uploader("인수인계서 PDF 업로드", type=["pdf"])
if uploaded is not None:
    st.write(f"파일: **{uploaded.name}**")
    item_options = {f"{r.item_name} / {r.spec} ({r.unit})": int(r.id) for _, r in items.iterrows()}
    selected_label = st.selectbox("연결 자재", list(item_options.keys()))
    qty = st.number_input("인수 수량", min_value=0.0, value=0.0, step=0.1)
    if st.button("인수인계서 등록", type="primary"):
        data = uploaded.getvalue()
        # DB에는 파일 자체 대신 파일명/연결품목/수량을 우선 기록하여 DB 용량 증가를 방지
        execute("""INSERT INTO material_documents(item_id,file_name,upload_date,extracted_text,applied_qty,status)
                   VALUES(?,?,?,?,?,?)""", (item_options[selected_label], uploaded.name, datetime.now().isoformat(timespec="seconds"), "", float(qty), "검토대기"))
        st.success("인수인계서를 등록했습니다. 입고 자동반영 전 검토대기 상태입니다.")
        st.rerun()

docs = read("""
SELECT d.id, d.file_name, d.upload_date, b.category, b.item_name, b.spec, b.unit,
       d.applied_qty, d.status
FROM material_documents d
LEFT JOIN budget_items b ON d.item_id=b.id
ORDER BY d.id DESC
""")
if len(docs):
    st.markdown("### 📋 인수인계서 등록현황")
    st.dataframe(docs.rename(columns={
        "file_name":"파일명","upload_date":"등록일","category":"공종","item_name":"품명",
        "spec":"규격","unit":"단위","applied_qty":"인수수량","status":"상태"
    }), use_container_width=True, hide_index=True)
