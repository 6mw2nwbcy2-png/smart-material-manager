from pathlib import Path

APP = Path('app.py')


def build_admin_block():
    return r'''elif menu == "관리자 설정":
    st.subheader("관리자 설정")
    if not is_admin():
        st.warning("관리자 로그인 후 사용할 수 있습니다.")
    else:
        st.markdown("### 예산 / 품목 관리")
        st.caption("공종별로 나누어 관리합니다. 기존 품목 수정과 신규 품목 추가는 각각 저장 버튼을 눌렀을 때만 DB에 반영됩니다.")

        admin_category = st.selectbox(
            "관리 공종",
            ["철근", "레미콘", "타일", "석재"],
            key="admin_category_filter_v2",
        )

        items = read(
            "SELECT * FROM budget_items WHERE category=? AND active=1 ORDER BY vendor,spec,item_name",
            (admin_category,),
        )

        if len(items):
            edit_cols = [
                "id", "vendor", "item_name", "spec", "unit", "budget_qty",
                "tile_type", "application_type", "default_destination"
            ]
            edit = items[edit_cols].copy()
            edit.columns = [
                "id", "협력사", "품명", "규격", "단위", "예산수량",
                "타일구분", "적용구분", "기본납품처"
            ]

            with st.form(f"admin_budget_form_{admin_category}"):
                if admin_category == "타일":
                    type_options = ["", "욕실 벽타일", "욕실 바닥타일", "테라스 타일", "펜트하우스 타일", "기타"]
                    app_options = ["", "일반세대 시스템욕실", "일반세대 기타", "테라스하우스", "펜트하우스"]
                    dest_options = ["", "현장", "시스템욕실 공장"]
                elif admin_category == "석재":
                    type_options = ["인조석", "천연가공석"]
                    app_options = [""]
                    dest_options = ["", "현장"]
                else:
                    type_options = [""]
                    app_options = [""]
                    dest_options = [""]

                edited = st.data_editor(
                    edit,
                    use_container_width=True,
                    hide_index=True,
                    disabled=["id"],
                    num_rows="fixed",
                    column_config={
                        "id": None,
                        "협력사": st.column_config.TextColumn("협력사"),
                        "품명": st.column_config.TextColumn("품명"),
                        "규격": st.column_config.TextColumn("규격"),
                        "단위": st.column_config.TextColumn("단위"),
                        "예산수량": st.column_config.NumberColumn("예산수량", min_value=0.0, step=0.1),
                        "타일구분": st.column_config.SelectboxColumn("타일구분", options=type_options),
                        "적용구분": st.column_config.SelectboxColumn("적용구분", options=app_options),
                        "기본납품처": st.column_config.SelectboxColumn("기본납품처", options=dest_options),
                    },
                    key=f"admin_budget_editor_{admin_category}",
                )
                save_existing = st.form_submit_button("현재 공종 품목 저장", type="primary")

            if save_existing:
                for _, r in edited.iterrows():
                    rid = int(r["id"])
                    vendor = str(r.get("협력사", "") or "").strip()
                    item_name = str(r.get("품명", "") or "").strip()
                    spec = str(r.get("규격", "") or "").strip()
                    unit = str(r.get("단위", "") or "").strip()
                    budget_qty = float(r.get("예산수량", 0) or 0)
                    tile_type = str(r.get("타일구분", "") or "").strip()
                    application_type = str(r.get("적용구분", "") or "").strip()
                    default_destination = str(r.get("기본납품처", "") or "").strip()
                    if admin_category == "타일" and not default_destination:
                        default_destination = calc_destination(tile_type, application_type)
                    if admin_category == "석재" and not tile_type:
                        tile_type = "인조석"
                    if not item_name or not unit:
                        continue
                    execute(
                        """UPDATE budget_items
                           SET vendor=?, item_name=?, spec=?, unit=?, budget_qty=?,
                               tile_type=?, application_type=?, default_destination=?
                           WHERE id=? AND category=?""",
                        (vendor, item_name, spec, unit, budget_qty, tile_type,
                         application_type, default_destination, rid, admin_category),
                    )
                st.success(f"{admin_category} 품목 저장 완료")
                st.rerun()
        else:
            st.info(f"등록된 {admin_category} 품목이 없습니다. 아래에서 신규 품목을 추가하세요.")

        st.markdown("---")
        st.markdown("### 신규 품목 추가")
        st.caption("신규 품목은 표의 빈 행을 추가하지 않고 별도 입력폼으로 등록합니다. 공종 변경 시 화면 오류를 방지합니다.")

        with st.form(f"admin_new_item_form_{admin_category}", clear_on_submit=True):
            n1, n2 = st.columns(2)
            new_vendor = n1.text_input("협력사")
            new_name = n2.text_input("품명")
            n3, n4 = st.columns(2)
            new_spec = n3.text_input("규격")
            new_unit = n4.text_input("단위", value="M" if admin_category == "석재" else "")
            n5, n6 = st.columns(2)
            new_qty = n5.number_input("예산수량", min_value=0.0, value=0.0, step=0.1)
            if admin_category == "타일":
                new_type = n6.selectbox("타일구분", ["욕실 벽타일", "욕실 바닥타일", "테라스 타일", "펜트하우스 타일", "기타"])
                new_app = st.selectbox("적용구분", ["일반세대 시스템욕실", "일반세대 기타", "테라스하우스", "펜트하우스"])
                new_dest = st.selectbox("기본납품처", ["현장", "시스템욕실 공장"])
            elif admin_category == "석재":
                new_type = n6.selectbox("석재구분", ["인조석", "천연가공석"])
                new_app = ""
                new_dest = "현장"
            else:
                new_type = ""
                new_app = ""
                new_dest = ""
            add_new = st.form_submit_button(f"{admin_category} 신규 품목 추가", type="primary")

        if add_new:
            if not new_name.strip() or not new_unit.strip():
                st.warning("품명과 단위를 입력해주세요.")
            else:
                dup = read(
                    "SELECT id FROM budget_items WHERE category=? AND item_name=? AND spec=? AND active=1",
                    (admin_category, new_name.strip(), new_spec.strip()),
                )
                if len(dup):
                    st.warning("같은 공종의 품명·규격이 이미 등록되어 있습니다.")
                else:
                    execute(
                        """INSERT INTO budget_items(
                               category,vendor,item_name,spec,unit,budget_qty,
                               tile_type,application_type,default_destination,active
                           ) VALUES(?,?,?,?,?,?,?,?,?,1)""",
                        (admin_category, new_vendor.strip(), new_name.strip(), new_spec.strip(),
                         new_unit.strip(), float(new_qty), new_type, new_app, new_dest),
                    )
                    st.success(f"{admin_category} 신규 품목이 추가되었습니다.")
                    st.rerun()
'''


def main():
    s = APP.read_text(encoding='utf-8')
    marker = 'elif menu == "관리자 설정":'
    start = s.index(marker)
    s = s[:start] + build_admin_block()
    APP.write_text(s, encoding='utf-8')


if __name__ == '__main__':
    main()
    print('fix_admin_category_editor: replaced admin editor')
