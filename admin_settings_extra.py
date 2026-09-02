import pandas as pd
import streamlit as st

st.subheader("관리자 설정")

if not is_admin():
    st.warning("관리자 로그인 후 사용할 수 있습니다.")
else:
    st.markdown("### 예산 / 품목 관리")
    st.caption("철근·레미콘·타일·석재를 한 표에서 여러 행 추가/수정할 수 있습니다. 삭제는 반드시 '삭제' 체크 후 저장해야 반영됩니다.")

    # 안전장치: 과거 일괄 저장 로직 때문에 모든 품목이 비활성화된 경우 자동 복구.
    _all_items = read("SELECT * FROM budget_items ORDER BY category,vendor,spec,item_name")
    _active_items = _all_items[_all_items["active"] == 1].copy() if len(_all_items) else _all_items.copy()
    if len(_all_items) and not len(_active_items):
        execute("UPDATE budget_items SET active=1")
        st.warning("이전 저장 과정에서 비활성화된 예산/품목을 자동 복구했습니다.")
        _all_items = read("SELECT * FROM budget_items ORDER BY category,vendor,spec,item_name")
        _active_items = _all_items[_all_items["active"] == 1].copy()

    items = _active_items
    edit_cols = ["id","category","vendor","item_name","spec","unit","budget_qty","tile_type","application_type","default_destination"]
    base = items[edit_cols].copy() if len(items) else pd.DataFrame(columns=edit_cols)
    base["삭제"] = False

    edited = st.data_editor(
        base,
        use_container_width=True,
        hide_index=True,
        disabled=["id"],
        num_rows="dynamic",
        column_config={
            "id": None,
            "category": st.column_config.SelectboxColumn("공종", options=["철근","레미콘","타일","석재"], required=True),
            "vendor": st.column_config.TextColumn("협력사"),
            "item_name": st.column_config.TextColumn("품명", required=True),
            "spec": st.column_config.TextColumn("규격"),
            "unit": st.column_config.TextColumn("단위", required=True),
            "budget_qty": st.column_config.NumberColumn("예산수량", min_value=0.0, step=0.1),
            "tile_type": st.column_config.TextColumn("타일/석재구분"),
            "application_type": st.column_config.TextColumn("적용구분"),
            "default_destination": st.column_config.TextColumn("기본납품처"),
            "삭제": st.column_config.CheckboxColumn("삭제", help="정말 삭제할 품목만 체크하세요."),
        },
        key="admin_bulk_budget_editor_v7",
    )

    if st.button("예산 / 품목 전체 저장", type="primary", key="admin_bulk_save_v7"):
        seen = set()
        errors = []
        delete_ids = []
        save_rows = []

        for idx, r in edited.iterrows():
            rid = r.get("id")
            if bool(r.get("삭제", False)):
                if pd.notna(rid):
                    delete_ids.append(int(rid))
                continue

            category = str(r.get("category", "") or "").strip()
            item_name = str(r.get("item_name", "") or "").strip()
            spec = str(r.get("spec", "") or "").strip()
            unit = str(r.get("unit", "") or "").strip()
            vendor = str(r.get("vendor", "") or "").strip()
            tile_type = str(r.get("tile_type", "") or "").strip()
            application_type = str(r.get("application_type", "") or "").strip()
            default_destination = str(r.get("default_destination", "") or "").strip()
            budget_qty = float(r.get("budget_qty", 0) or 0)

            if not category and not item_name and not unit:
                continue
            if not category or not item_name or not unit:
                errors.append(f"{idx+1}행: 공종·품명·단위는 필수입니다.")
                continue

            key = (category, item_name, spec)
            if key in seen:
                errors.append(f"{idx+1}행: 같은 공종/품명/규격이 중복되었습니다.")
                continue
            seen.add(key)

            if category == "타일" and not default_destination:
                default_destination = calc_destination(tile_type, application_type)
            if category == "석재":
                if not tile_type:
                    tile_type = "인조석"
                if not default_destination:
                    default_destination = "현장"

            save_rows.append((rid, category, vendor, item_name, spec, unit, budget_qty, tile_type, application_type, default_destination))

        if errors:
            st.error("저장하지 못한 행이 있습니다: " + " / ".join(errors))
        else:
            for row in save_rows:
                rid, category, vendor, item_name, spec, unit, budget_qty, tile_type, application_type, default_destination = row
                if pd.notna(rid):
                    execute(
                        """UPDATE budget_items
                           SET category=?,vendor=?,item_name=?,spec=?,unit=?,budget_qty=?,
                               tile_type=?,application_type=?,default_destination=?,active=1
                           WHERE id=?""",
                        (category,vendor,item_name,spec,unit,budget_qty,tile_type,
                         application_type,default_destination,int(rid)),
                    )
                else:
                    dup = read(
                        "SELECT id FROM budget_items WHERE category=? AND item_name=? AND spec=? AND active=1",
                        (category,item_name,spec),
                    )
                    if len(dup):
                        continue
                    execute(
                        """INSERT INTO budget_items(
                           category,vendor,item_name,spec,unit,budget_qty,
                           tile_type,application_type,default_destination,active)
                           VALUES(?,?,?,?,?,?,?,?,?,1)""",
                        (category,vendor,item_name,spec,unit,budget_qty,tile_type,
                         application_type,default_destination),
                    )

            # 삭제는 명시적으로 체크된 기존 품목에만 적용. 표에서 행이 사라졌다는 이유로 자동 삭제하지 않음.
            for rid in delete_ids:
                execute("UPDATE budget_items SET active=0 WHERE id=?", (rid,))

            msg = "예산 / 품목 저장 완료"
            if delete_ids:
                msg += f" · 삭제 {len(delete_ids)}건"
            st.success(msg)
            st.rerun()

    inactive = read("SELECT id,category,vendor,item_name,spec,unit,budget_qty FROM budget_items WHERE active=0 ORDER BY category,vendor,spec,item_name")
    if len(inactive):
        with st.expander(f"비활성 품목 복구 ({len(inactive)}건)"):
            restore = inactive.copy()
            restore["복구"] = False
            restore_edit = st.data_editor(
                restore,
                use_container_width=True,
                hide_index=True,
                disabled=["id","category","vendor","item_name","spec","unit","budget_qty"],
                column_config={"id": None, "복구": st.column_config.CheckboxColumn("복구")},
                key="admin_restore_inactive_v1",
            )
            restore_ids = restore_edit.loc[restore_edit["복구"] == True, "id"].tolist()
            if st.button("선택 품목 복구", disabled=not len(restore_ids), key="admin_restore_inactive_btn_v1"):
                for rid in restore_ids:
                    execute("UPDATE budget_items SET active=1 WHERE id=?", (int(rid),))
                st.success(f"{len(restore_ids)}개 품목 복구 완료")
                st.rerun()

    st.markdown("---")
    st.markdown("### 저장된 발주서 관리 / 삭제")
    st.caption("관리자는 저장된 발주서의 결재상태를 수정하거나 잘못 저장된 발주서를 선택하여 삭제할 수 있습니다.")

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
        for col in ["협력사 확인", "결재 완료", "발주 완료"]:
            order_edit[col] = order_edit[col].fillna(0).astype(bool)
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
            key="admin_saved_order_delete_editor_v2",
        )

        c1, c2 = st.columns(2)
        if c1.button("발주서 상태 저장", type="primary", key="admin_saved_order_status_save_v2"):
            for _, r in order_result.iterrows():
                execute(
                    "UPDATE orders SET partner_confirm=?,internal_approval=?,order_complete=? WHERE id=?",
                    (
                        int(bool(r["협력사 확인"])),
                        int(bool(r["결재 완료"])),
                        int(bool(r["발주 완료"])),
                        int(r["id"]),
                    ),
                )
            st.success("발주서 상태 저장 완료")
            st.rerun()

        selected_delete = order_result[order_result["삭제 선택"] == True].copy()
        delete_confirm = c2.checkbox(
            f"선택한 {len(selected_delete)}건 삭제 확인",
            key="admin_saved_order_delete_confirm_v2",
        )
        if c2.button(
            "선택 발주서 삭제",
            key="admin_saved_order_delete_v2",
            disabled=(not delete_confirm or not len(selected_delete)),
        ):
            deleted = 0
            for _, r in selected_delete.iterrows():
                oid = int(r["id"])
                order_no = str(r["발주번호"])
                try:
                    execute("DELETE FROM order_attachments WHERE order_id=?", (oid,))
                except Exception:
                    pass
                try:
                    execute(
                        "DELETE FROM transactions WHERE tx_type='발주' AND note LIKE ?",
                        (f"%{order_no}%",),
                    )
                except Exception:
                    pass
                execute("DELETE FROM order_lines WHERE order_id=?", (oid,))
                execute("DELETE FROM orders WHERE id=?", (oid,))
                deleted += 1
            st.success(f"선택한 발주서 {deleted}건 삭제 완료")
            st.rerun()

    st.markdown("---")
    st.markdown("### 관리자 비밀번호 변경")
    p1 = st.text_input("새 비밀번호", type="password", key="admin_pw1_v7")
    p2 = st.text_input("새 비밀번호 확인", type="password", key="admin_pw2_v7")
    if st.button("비밀번호 변경", key="admin_pw_change_v7"):
        if len(p1) < 4:
            st.warning("4자리 이상 입력하세요.")
        elif p1 != p2:
            st.warning("비밀번호가 서로 다릅니다.")
        else:
            execute("UPDATE settings SET value=? WHERE key='admin_password'", (sha(p1),))
            st.success("비밀번호 변경 완료")
