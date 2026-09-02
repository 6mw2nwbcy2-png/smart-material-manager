import pandas as pd
import streamlit as st

st.subheader("관리자 설정")

if not is_admin():
    st.warning("관리자 로그인 후 사용할 수 있습니다.")
else:
    # ------------------------------------------------------------------
    # 1) 저장된 예산/품목: 완전 읽기 전용
    # ------------------------------------------------------------------
    st.markdown("### 기존 예산 현황")
    st.info("🔒 한 번 저장된 예산/품목의 핵심 내역은 수정하거나 삭제할 수 없습니다. 잘못 입력하지 않도록 신규 저장 전에 확인해주세요.")

    _budget_all = read(
        """SELECT id,category,vendor,item_name,spec,unit,budget_qty,
                  tile_type,application_type,default_destination,
                  COALESCE(planned_delivery_date,'') AS planned_delivery_date,
                  COALESCE(storage_location,'') AS storage_location
           FROM budget_items
           WHERE active=1
           ORDER BY category,vendor,spec,item_name"""
    )

    if len(_budget_all):
        _budget_filter = st.selectbox(
            "예산 공종",
            ["전체", "철근", "레미콘", "타일", "석재"],
            key="admin_budget_history_filter_locked_v1",
        )
        _budget_show = _budget_all.copy()
        if _budget_filter != "전체":
            _budget_show = _budget_show[_budget_show["category"] == _budget_filter].copy()
        _budget_show = _budget_show[[
            "category", "vendor", "item_name", "spec", "unit", "budget_qty",
            "tile_type", "application_type", "default_destination",
            "planned_delivery_date", "storage_location"
        ]]
        _budget_show.columns = [
            "공종", "협력사", "품명", "규격", "단위", "예산수량",
            "타일/석재구분", "적용구분", "기본납품처", "현장반입 예정일", "보관위치"
        ]
        st.dataframe(_budget_show, use_container_width=True, hide_index=True)
    else:
        st.info("저장된 예산 품목이 없습니다.")

    # ------------------------------------------------------------------
    # 2) 신규 예산/품목만 추가 가능. 저장 후에는 잠김.
    # ------------------------------------------------------------------
    st.markdown("---")
    st.markdown("### 신규 예산 / 품목 추가")
    st.caption("여러 행을 한 번에 입력할 수 있습니다. 저장된 행은 이후 수정/삭제가 차단됩니다.")

    _blank = {
        "category": "", "vendor": "", "item_name": "", "spec": "",
        "unit": "", "budget_qty": 0.0, "tile_type": "",
        "application_type": "", "default_destination": ""
    }
    _new_base = pd.DataFrame([_blank.copy() for _ in range(5)])
    _new_edit = st.data_editor(
        _new_base,
        use_container_width=True,
        hide_index=True,
        num_rows="dynamic",
        column_config={
            "category": st.column_config.SelectboxColumn("공종", options=["", "철근", "레미콘", "타일", "석재"]),
            "vendor": st.column_config.TextColumn("협력사"),
            "item_name": st.column_config.TextColumn("품명"),
            "spec": st.column_config.TextColumn("규격"),
            "unit": st.column_config.TextColumn("단위"),
            "budget_qty": st.column_config.NumberColumn("예산수량", min_value=0.0, step=0.1),
            "tile_type": st.column_config.TextColumn("타일/석재구분"),
            "application_type": st.column_config.TextColumn("적용구분"),
            "default_destination": st.column_config.TextColumn("기본납품처"),
        },
        key="admin_new_budget_append_only_v1",
    )

    _confirm_budget_lock = st.checkbox(
        "저장 후 해당 예산/품목은 수정·삭제할 수 없음을 확인했습니다.",
        key="admin_new_budget_lock_confirm_v1",
    )
    if st.button(
        "신규 예산 / 품목 저장",
        type="primary",
        disabled=not _confirm_budget_lock,
        key="admin_new_budget_append_save_v1",
    ):
        _errors = []
        _rows = []
        _seen = set()
        for _idx, _r in _new_edit.iterrows():
            _category = str(_r.get("category", "") or "").strip()
            _vendor = str(_r.get("vendor", "") or "").strip()
            _item_name = str(_r.get("item_name", "") or "").strip()
            _spec = str(_r.get("spec", "") or "").strip()
            _unit = str(_r.get("unit", "") or "").strip()
            _tile_type = str(_r.get("tile_type", "") or "").strip()
            _application_type = str(_r.get("application_type", "") or "").strip()
            _destination = str(_r.get("default_destination", "") or "").strip()
            _budget_qty = float(_r.get("budget_qty", 0) or 0)

            if not any([_category, _vendor, _item_name, _spec, _unit, _tile_type, _application_type, _destination, _budget_qty]):
                continue
            if not _category or not _item_name or not _unit:
                _errors.append(f"{_idx + 1}행: 공종·품명·단위는 필수입니다.")
                continue

            _key = (_category, _item_name, _spec)
            if _key in _seen:
                _errors.append(f"{_idx + 1}행: 같은 공종/품명/규격이 입력표 안에서 중복됩니다.")
                continue
            _seen.add(_key)

            _dup = read(
                "SELECT id FROM budget_items WHERE category=? AND item_name=? AND spec=? LIMIT 1",
                (_category, _item_name, _spec),
            )
            if len(_dup):
                _errors.append(f"{_idx + 1}행: 이미 저장된 동일 공종/품명/규격이 있습니다.")
                continue

            if _category == "타일" and not _destination:
                _destination = calc_destination(_tile_type, _application_type)
            if _category == "석재":
                if not _tile_type:
                    _tile_type = "인조석"
                if not _destination:
                    _destination = "현장"

            _rows.append((
                _category, _vendor, _item_name, _spec, _unit, _budget_qty,
                _tile_type, _application_type, _destination
            ))

        if _errors:
            st.error("저장하지 못했습니다. " + " / ".join(_errors))
        elif not _rows:
            st.warning("저장할 신규 품목을 입력해주세요.")
        else:
            for _row in _rows:
                execute(
                    """INSERT INTO budget_items(
                           category,vendor,item_name,spec,unit,budget_qty,
                           tile_type,application_type,default_destination,active)
                       VALUES(?,?,?,?,?,?,?,?,?,1)""",
                    _row,
                )
            st.success(f"신규 예산/품목 {_rows.__len__()}건 저장 완료 · 이제 수정/삭제가 잠겼습니다.")
            st.rerun()

    # ------------------------------------------------------------------
    # 3) 저장된 투입내역: 완전 읽기 전용
    # ------------------------------------------------------------------
    st.markdown("---")
    st.markdown("### 저장된 투입내역")
    st.info("🔒 저장 완료된 투입내역은 관리자도 수정하거나 삭제할 수 없습니다.")
    _used = read(
        """SELECT t.id,t.tx_date,b.category,b.vendor,b.item_name,b.spec,b.unit,
                  t.qty,t.destination,t.note,t.input_user
           FROM transactions t
           JOIN budget_items b ON b.id=t.item_id
           WHERE t.tx_type='투입'
           ORDER BY t.id DESC"""
    )
    if len(_used):
        _used_show = _used[[
            "tx_date","category","vendor","item_name","spec","unit",
            "qty","destination","note","input_user"
        ]].copy()
        _used_show.columns = [
            "투입일","공종","협력사","품명","규격","단위",
            "투입수량","위치/납품처","비고","입력자"
        ]
        st.dataframe(_used_show, use_container_width=True, hide_index=True)
    else:
        st.info("저장된 투입내역이 없습니다.")

    # ------------------------------------------------------------------
    # 4) 발주서는 상태 수정/삭제 가능 (투입내역에는 영향 없음)
    # ------------------------------------------------------------------
    st.markdown("---")
    st.markdown("### 저장된 발주서 관리 / 삭제")
    st.caption("관리자는 발주서 상태를 수정하거나 잘못 저장된 발주서를 선택하여 삭제할 수 있습니다. 저장된 투입내역은 삭제하지 않습니다.")

    admin_orders = read("SELECT * FROM orders ORDER BY id DESC")
    if not len(admin_orders):
        st.info("저장된 발주서가 없습니다.")
    else:
        order_edit = admin_orders[[
            "id", "order_no", "category", "vendor", "order_date",
            "partner_confirm", "internal_approval", "order_complete"
        ]].copy()
        order_edit.columns = [
            "id", "발주번호", "공종", "협력사", "발주일",
            "협력사 확인", "결재 완료", "발주 완료"
        ]
        for _col in ["협력사 확인", "결재 완료", "발주 완료"]:
            order_edit[_col] = order_edit[_col].fillna(0).astype(bool)
        order_edit["삭제 선택"] = False

        order_result = st.data_editor(
            order_edit,
            use_container_width=True,
            hide_index=True,
            disabled=["id", "발주번호", "공종", "협력사", "발주일"],
            column_config={
                "id": None,
                "협력사 확인": st.column_config.CheckboxColumn("협력사 확인"),
                "결재 완료": st.column_config.CheckboxColumn("결재 완료"),
                "발주 완료": st.column_config.CheckboxColumn("발주 완료"),
                "삭제 선택": st.column_config.CheckboxColumn("삭제 선택"),
            },
            key="admin_saved_order_delete_editor_v3",
        )

        _c1, _c2 = st.columns(2)
        if _c1.button("발주서 상태 저장", type="primary", key="admin_saved_order_status_save_v3"):
            for _, _r in order_result.iterrows():
                execute(
                    "UPDATE orders SET partner_confirm=?,internal_approval=?,order_complete=? WHERE id=?",
                    (
                        int(bool(_r["협력사 확인"])),
                        int(bool(_r["결재 완료"])),
                        int(bool(_r["발주 완료"])),
                        int(_r["id"]),
                    ),
                )
            st.success("발주서 상태 저장 완료")
            st.rerun()

        _selected_delete = order_result[order_result["삭제 선택"] == True].copy()
        _delete_confirm = _c2.checkbox(
            f"선택한 {len(_selected_delete)}건 삭제 확인",
            key="admin_saved_order_delete_confirm_v3",
        )
        if _c2.button(
            "선택 발주서 삭제",
            key="admin_saved_order_delete_v3",
            disabled=(not _delete_confirm or not len(_selected_delete)),
        ):
            _deleted = 0
            for _, _r in _selected_delete.iterrows():
                _oid = int(_r["id"])
                _order_no = str(_r["발주번호"])
                try:
                    execute("DELETE FROM order_attachments WHERE order_id=?", (_oid,))
                except Exception:
                    pass
                # 발주서 삭제 시 '발주' 거래만 삭제. '투입' 거래는 DB 보호장치상 삭제 불가.
                execute(
                    "DELETE FROM transactions WHERE tx_type='발주' AND note LIKE ?",
                    (f"%{_order_no}%",),
                )
                execute("DELETE FROM order_lines WHERE order_id=?", (_oid,))
                execute("DELETE FROM orders WHERE id=?", (_oid,))
                _deleted += 1
            st.success(f"선택한 발주서 {_deleted}건 삭제 완료")
            st.rerun()

    # ------------------------------------------------------------------
    # 5) 관리자 비밀번호
    # ------------------------------------------------------------------
    st.markdown("---")
    st.markdown("### 관리자 비밀번호 변경")
    p1 = st.text_input("새 비밀번호", type="password", key="admin_pw1_locked_v1")
    p2 = st.text_input("새 비밀번호 확인", type="password", key="admin_pw2_locked_v1")
    if st.button("비밀번호 변경", key="admin_pw_change_locked_v1"):
        if len(p1) < 4:
            st.warning("4자리 이상 입력하세요.")
        elif p1 != p2:
            st.warning("비밀번호가 서로 다릅니다.")
        else:
            execute("UPDATE settings SET value=? WHERE key='admin_password'", (sha(p1),))
            st.success("비밀번호 변경 완료")
