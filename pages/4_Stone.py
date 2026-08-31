import io
import sqlite3
from pathlib import Path
from datetime import date

import pandas as pd
import streamlit as st

DB = Path("material_manager_v11.db")
CATEGORY = "석재"
STONE_TYPES = ["인조석", "천연가공석"]


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
            destination TEXT DEFAULT '',
            delivery_recipient TEXT DEFAULT '',
            delivery_phone TEXT DEFAULT '',
            delivery_address TEXT DEFAULT ''
        )""")
        c.commit()


ensure_schema()

st.title("석재 관리")
st.caption("안정화 모드 · 백업 DB")

items = read("SELECT id,vendor,item_name,spec,unit,budget_qty,tile_type,default_destination FROM budget_items WHERE category=? AND active=1 ORDER BY vendor,item_name,spec", (CATEGORY,))

if items.empty:
    with st.form("stone_seed_form"):
        st.info("등록된 석재 품목이 없습니다.")
        if st.form_submit_button("기본 석재 품목 만들기"):
            for stone_type in STONE_TYPES:
                execute("INSERT INTO budget_items(category,vendor,item_name,spec,unit,budget_qty,tile_type,application_type,default_destination,active) VALUES(?,?,?,?,?,?,?,?,?,1)", (CATEGORY,"",stone_type,"","M",0.0,stone_type,"","현장"))
            st.rerun()
else:
    totals = read("""
        SELECT b.id,b.vendor,b.item_name,b.spec,b.unit,b.budget_qty,b.tile_type,
               COALESCE(SUM(CASE WHEN t.tx_type='발주' THEN t.qty ELSE 0 END),0) ordered,
               COALESCE(SUM(CASE WHEN t.tx_type='입고' THEN t.qty ELSE 0 END),0) received,
               COALESCE(SUM(CASE WHEN t.tx_type='투입' THEN t.qty ELSE 0 END),0) used
        FROM budget_items b
        LEFT JOIN transactions t ON b.id=t.item_id
        WHERE b.category=? AND b.active=1
        GROUP BY b.id
        ORDER BY b.vendor,b.item_name,b.spec
    """, (CATEGORY,))
    totals["재고"] = totals["received"] - totals["used"]
    st.dataframe(totals, use_container_width=True, hide_index=True)

    st.markdown("### 석재 입고 / 투입 입력")
    with st.form("stone_tx_form"):
        labels = [f"{r.item_name} {r.spec}".strip() for _, r in items.iterrows()]
        selected = st.selectbox("품목", labels)
        idx = labels.index(selected)
        item_id = int(items.iloc[idx]["id"])
        tx_type = st.selectbox("구분", ["입고","투입"])
        tx_date = st.date_input("일자", value=date.today())
        qty = st.number_input("수량", min_value=0.0, step=0.1)
        note = st.text_input("비고")
        saved = st.form_submit_button("저장", type="primary")
    if saved:
        if qty <= 0:
            st.warning("수량을 입력해주세요.")
        else:
            execute("INSERT INTO transactions(tx_date,item_id,tx_type,qty,destination,note,input_user) VALUES(?,?,?,?,?,?,?)", (str(tx_date),item_id,tx_type,float(qty),"",note,""))
            st.success("저장되었습니다.")
            st.rerun()

    st.markdown("### 석재 발주")
    with st.form("stone_order_form"):
        vendor = st.text_input("협력사")
        order_date = st.date_input("발주일", value=date.today(), key="stone_order_date")
        destination = st.text_input("납품처", value="현장")
        recipient = st.text_input("받는 사람")
        phone = st.text_input("연락처")
        address = st.text_input("주소")
        qties = {}
        for _, r in items.iterrows():
            label = f"{r['item_name']} {r['spec']} ({r['unit']})".strip()
            qties[int(r['id'])] = st.number_input(label, min_value=0.0, step=0.1, key=f"stone_order_qty_{int(r['id'])}")
        requested = st.date_input("납품요청일", value=date.today(), key="stone_req_date")
        note = st.text_area("비고")
        submit = st.form_submit_button("발주 저장", type="primary")
    if submit:
        selected_rows = [(item_id, q) for item_id, q in qties.items() if q > 0]
        if not selected_rows:
            st.warning("발주 수량을 입력해주세요.")
        else:
            prefix = order_date.strftime("%Y%m%d")
            existing = read("SELECT order_no FROM orders WHERE order_no LIKE ?", (f"{prefix}-%",))
            nums = []
            for x in existing["order_no"] if len(existing) else []:
                try: nums.append(int(str(x).split("-")[-1]))
                except Exception: pass
            order_no = f"{prefix}-{(max(nums)+1 if nums else 1):03d}"
            execute("INSERT INTO orders(order_no,category,vendor,order_date,partner_confirm,internal_approval,order_complete,note) VALUES(?,?,?,?,0,0,0,?)", (order_no,CATEGORY,vendor.strip(),str(order_date),note))
            order_id = int(read("SELECT id FROM orders WHERE order_no=?", (order_no,)).iloc[0]["id"])
            for item_id, q in selected_rows:
                execute("INSERT INTO order_lines(order_id,item_id,qty,requested_delivery_date,destination,delivery_recipient,delivery_phone,delivery_address) VALUES(?,?,?,?,?,?,?,?)", (order_id,item_id,float(q),str(requested),destination.strip(),recipient.strip(),phone.strip(),address.strip()))
                execute("INSERT INTO transactions(tx_date,item_id,tx_type,qty,destination,note,input_user) VALUES(?,?,?,?,?,?,?)", (str(order_date),item_id,"발주",float(q),destination.strip(),f"발주번호 {order_no}",""))
            st.success(f"발주 저장 완료: {order_no}")
            st.rerun()
