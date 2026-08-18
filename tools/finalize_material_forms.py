from pathlib import Path

APP = Path('app.py')


def patch_app():
    s = APP.read_text(encoding='utf-8')

    # Stone is a first-class budget/dashboard category.
    s = s.replace('for cat in ["철근","레미콘","타일"]:', 'for cat in ["철근","레미콘","타일","석재"]:')
    s = s.replace('options=["철근","레미콘","타일"]', 'options=["철근","레미콘","타일","석재"]')

    # Common input form: typing never writes to DB until the explicit save button.
    use_start = '    st.markdown("### 투입내역 입력")'
    admin_start = '    if is_admin():'
    use_i = s.index(use_start)
    admin_i = s.index(admin_start, use_i)
    use_block = '''    st.markdown("### 투입내역 입력")
    st.caption("입력 중에는 DB에 저장되지 않습니다. 모든 값을 입력한 뒤 마지막 저장 버튼을 눌러주세요.")
    use_df = disp.copy()
    use_df["이번 투입"] = 0.0
    disabled = [c for c in use_df.columns if c != "이번 투입"]
    with st.form(f"use_form_{cat}"):
        use_edit = st.data_editor(
            use_df, use_container_width=True, hide_index=True, disabled=disabled,
            column_config={"id": None, "이번 투입": st.column_config.NumberColumn(min_value=0.0, step=0.1)},
            key=f"use_{cat}",
        )
        a, b = st.columns(2)
        use_date = a.date_input("투입일", date.today(), key=f"use_date_{cat}")
        input_user = b.text_input("입력자", key=f"user_{cat}", placeholder="예: 김OO")
        note = st.text_input("투입 비고", key=f"use_note_{cat}")
        save_use = st.form_submit_button(f"{cat} 투입 저장", type="primary")
    if save_use:
        count = 0
        for _, r in use_edit.iterrows():
            q = float(r["이번 투입"] or 0)
            if q > 0:
                destination = r.get("납품처", "") if cat == "타일" else ""
                execute("""INSERT INTO transactions(tx_date,item_id,tx_type,qty,destination,note,input_user)
                           VALUES(?,?,?,?,?,?,?)""", (str(use_date), int(r["id"]), "투입", q, destination, note, input_user.strip()))
                count += 1
        if count:
            st.success(f"{count}개 품목 투입내역 저장 완료")
            st.rerun()
        else:
            st.warning("투입수량을 입력하세요.")

'''
    s = s[:use_i] + use_block + s[admin_i:]

    # Admin order/receipt entry is also one explicit form submission.
    admin_i = s.index(admin_start, use_i)
    tile_i = s.index('    if cat == "타일":', admin_i)
    admin_block = '''    if is_admin():
        st.markdown("---")
        st.markdown("### 관리자 입력 — 발주 / 입고")
        st.caption("발주·입고 수량과 기준일을 모두 입력한 뒤 저장 버튼을 눌러주세요. 입력 중에는 DB에 저장되지 않습니다.")
        adm = disp.copy()
        adm["이번 발주"] = 0.0
        adm["이번 입고"] = 0.0
        disabled2 = [c for c in adm.columns if c not in ["이번 발주", "이번 입고"]]
        with st.form(f"adm_form_{cat}"):
            adm_edit = st.data_editor(
                adm, use_container_width=True, hide_index=True, disabled=disabled2,
                column_config={
                    "id": None,
                    "이번 발주": st.column_config.NumberColumn(min_value=0.0, step=0.1),
                    "이번 입고": st.column_config.NumberColumn(min_value=0.0, step=0.1),
                }, key=f"adm_{cat}",
            )
            adm_date = st.date_input("발주/입고 기준일", date.today(), key=f"adm_date_{cat}")
            save_adm = st.form_submit_button("관리자 발주/입고 저장", type="primary")
        if save_adm:
            count = 0
            for _, r in adm_edit.iterrows():
                destination = r.get("납품처", "") if cat == "타일" else ""
                for col, typ in [("이번 발주", "발주"), ("이번 입고", "입고")]:
                    q = float(r[col] or 0)
                    if q > 0:
                        execute("""INSERT INTO transactions(tx_date,item_id,tx_type,qty,destination,note,input_user)
                                   VALUES(?,?,?,?,?,?,?)""", (str(adm_date), int(r["id"]), typ, q, destination, "관리자입력", "관리자"))
                        count += 1
            if count:
                st.success(f"{count}건 저장 완료")
                st.rerun()
            else:
                st.warning("발주 또는 입고 수량을 입력하세요.")

'''
    s = s[:admin_i] + admin_block + s[tile_i:]

    # Tile order form: all fields are inside one form, so typing does not persist/save per field.
    branch_i = s.index('    if cat == "타일":', admin_i)
    next_i = s.index('elif menu == "발주/결재 현황":', branch_i)
    tile_block = '''    if cat == "타일":
        st.markdown("---")
        st.markdown("### 타일 발주서 작성")
        st.info("품목·납품정보·발주 비고를 모두 입력한 뒤 마지막 저장 버튼을 눌러주세요. 입력 중에는 DB에 저장되지 않습니다.")
        vendors = [x for x in sorted(df.vendor.dropna().unique()) if str(x).strip()]
        if vendors:
            with st.form("tile_order_form"):
                vendor = st.selectbox("협력사", vendors)
                odf = df[df.vendor == vendor].copy()
                req = odf[["id", "item_name", "spec", "tile_type", "application_type", "unit", "budget_qty", "ordered"]].copy()
                req.columns = ["id", "품명", "규격", "타일구분", "적용구분", "단위", "예산", "누적발주"]
                req["발주수량"] = 0.0
                req["납품요청일"] = date.today()
                st.markdown("#### 품목 선택")
                req_edit = st.data_editor(
                    req, use_container_width=True, hide_index=True,
                    disabled=["id", "품명", "규격", "타일구분", "적용구분", "단위", "예산", "누적발주"],
                    column_config={
                        "id": None,
                        "발주수량": st.column_config.NumberColumn(min_value=0.0, step=0.1),
                        "납품요청일": st.column_config.DateColumn(format="YYYY-MM-DD"),
                    }, key="tile_multi_order",
                )
                st.markdown("#### 납품 정보")
                delivery_type = st.radio("납품구분", ["시스템욕실 공장", "현장"], horizontal=True)
                d1, d2 = st.columns(2)
                delivery_recipient = d1.text_input("받는 사람")
                delivery_phone = d2.text_input("연락처")
                site_df = read("SELECT value FROM settings WHERE key='site_address'")
                default_site_address = str(site_df.iloc[0]["value"]) if len(site_df) else ""
                if delivery_type == "현장":
                    delivery_address = st.text_input("현장 주소", value=default_site_address)
                else:
                    delivery_address = st.text_input("시스템욕실 공장 주소")
                c1, c2 = st.columns(2)
                order_date = c1.date_input("발주일", date.today(), key="tile_multi_order_date")
                order_note = c2.text_input("발주 비고", key="tile_multi_order_note")
                submit_tile_order = st.form_submit_button("선택 품목 일괄 발주 + PDF 생성", type="primary")

            if submit_tile_order:
                selected = req_edit[req_edit["발주수량"] > 0].copy()
                if not len(selected):
                    st.warning("발주수량을 입력한 품목이 없습니다.")
                elif not delivery_recipient.strip() or not delivery_phone.strip() or not delivery_address.strip():
                    st.warning("받는 사람·연락처·납품 주소를 모두 입력해주세요.")
                else:
                    order_date_str = order_date.strftime("%Y%m%d")
                    existing_orders = read("SELECT order_no FROM orders WHERE order_no LIKE ?", (f"{order_date_str}-%",))
                    numbers = []
                    for x in existing_orders["order_no"] if len(existing_orders) else []:
                        try:
                            numbers.append(int(str(x).split("-")[-1]))
                        except Exception:
                            pass
                    seq = max(numbers) + 1 if numbers else 1
                    order_no = f"{order_date_str}-{seq:03d}"
                    execute("""INSERT INTO orders(order_no,category,vendor,order_date,note) VALUES(?,?,?,?,?)""", (order_no, "타일", vendor, str(order_date), order_note.strip()))
                    oid = int(read("SELECT id FROM orders WHERE order_no=?", (order_no,)).iloc[0]["id"])
                    for _, r in selected.iterrows():
                        item_id = int(r["id"])
                        qty = float(r["발주수량"])
                        d = pd.to_datetime(r["납품요청일"]).date().isoformat()
                        execute("""INSERT INTO order_lines(order_id,item_id,qty,requested_delivery_date,destination,delivery_recipient,delivery_phone,delivery_address)
                                   VALUES(?,?,?,?,?,?,?,?)""", (oid, item_id, qty, d, delivery_type, delivery_recipient.strip(), delivery_phone.strip(), delivery_address.strip()))
                        execute("""INSERT INTO transactions(tx_date,item_id,tx_type,qty,destination,note,input_user)
                                   VALUES(?,?,?,?,?,?,?)""", (str(order_date), item_id, "발주", qty, delivery_type, f"발주서 {order_no}", st.session_state.get("multi_order_writer", "") or "일반사용자"))
                    lines = read("""SELECT b.item_name,b.spec,b.unit,ol.qty,ol.destination,ol.requested_delivery_date,ol.delivery_recipient,ol.delivery_phone,ol.delivery_address
                                   FROM order_lines ol JOIN budget_items b ON ol.item_id=b.id
                                   WHERE ol.order_id=? ORDER BY ol.requested_delivery_date,ol.id""", (oid,))
                    order_row = read("SELECT * FROM orders WHERE id=?", (oid,)).iloc[0]
                    st.session_state["last_pdf"] = make_order_pdf(order_row, lines)
                    st.session_state["last_pdf_name"] = f"{order_no}_발주서.pdf"
                    st.success(f"{len(selected)}개 품목이 한 장의 발주서로 생성되었습니다.")
                    st.rerun()

            if st.session_state.get("last_pdf"):
                st.download_button("📄 일괄 발주서 PDF 다운로드", st.session_state["last_pdf"], file_name=st.session_state["last_pdf_name"], mime="application/pdf", type="primary")
        else:
            st.info("등록된 타일 협력사가 없습니다.")

'''
    s = s[:branch_i] + tile_block + s[next_i:]
    APP.write_text(s, encoding='utf-8')


if __name__ == '__main__':
    patch_app()
    print('finalize_material_forms: app.py patched')
