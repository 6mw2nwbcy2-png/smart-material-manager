import pandas as pd
import streamlit as st

st.subheader("관리자 설정")

if not is_admin():
    st.warning("관리자 로그인 후 사용할 수 있습니다.")
else:
    st.markdown("### 예산 / 품목 관리")
    st.caption("철근·레미콘·타일·석재를 한 표에서 여러 행 추가/수정/삭제한 뒤 저장 버튼 한 번으로 반영합니다.")

    items = read("SELECT * FROM budget_items WHERE active=1 ORDER BY category,vendor,spec,item_name")
    edit_cols = ["id","category","vendor","item_name","spec","unit","budget_qty","tile_type","application_type","default_destination"]
    base = items[edit_cols].copy() if len(items) else pd.DataFrame(columns=edit_cols)

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
        },
        key="admin_bulk_budget_editor_v6",
    )

    if st.button("예산 / 품목 전체 저장", type="primary", key="admin_bulk_save_v6"):
        current_ids = set(items["id"].astype(int).tolist()) if len(items) else set()
        edited_ids = set()
        seen = set()
        errors = []

        for idx, r in edited.iterrows():
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

            rid = r.get("id")
            if pd.notna(rid):
                rid = int(rid)
                edited_ids.add(rid)
                execute(
                    """UPDATE budget_items
                       SET category=?,vendor=?,item_name=?,spec=?,unit=?,budget_qty=?,
                           tile_type=?,application_type=?,default_destination=?,active=1
                       WHERE id=?""",
                    (category,vendor,item_name,spec,unit,budget_qty,tile_type,
                     application_type,default_destination,rid),
                )
            else:
                dup = read(
                    "SELECT id FROM budget_items WHERE category=? AND item_name=? AND spec=? AND active=1",
                    (category,item_name,spec),
                )
                if len(dup):
                    errors.append(f"{idx+1}행: 이미 등록된 품목입니다.")
                    continue
                execute(
                    """INSERT INTO budget_items(
                       category,vendor,item_name,spec,unit,budget_qty,
                       tile_type,application_type,default_destination,active)
                       VALUES(?,?,?,?,?,?,?,?,?,1)""",
                    (category,vendor,item_name,spec,unit,budget_qty,tile_type,
                     application_type,default_destination),
                )

        if errors:
            st.error("저장하지 못한 행이 있습니다: " + " / ".join(errors))
        else:
            for rid in current_ids - edited_ids:
                execute("UPDATE budget_items SET active=0 WHERE id=?", (rid,))
            st.success("예산 / 품목 전체 저장 완료")
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
            key="admin_saved_order_delete_editor_v1",
        )

        c1, c2 = st.columns(2)
        if c1.button("발주서 상태 저장", type="primary", key="admin_saved_order_status_save_v1"):
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
            key="admin_saved_order_delete_confirm_v1",
        )
        if c2.button(
            "선택 발주서 삭제",
            key="admin_saved_order_delete_v1",
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
    p1 = st.text_input("새 비밀번호", type="password", key="admin_pw1_v6")
    p2 = st.text_input("새 비밀번호 확인", type="password", key="admin_pw2_v6")
    if st.button("비밀번호 변경", key="admin_pw_change_v6"):
        if len(p1) < 4:
            st.warning("4자리 이상 입력하세요.")
        elif p1 != p2:
            st.warning("비밀번호가 서로 다릅니다.")
        else:
            execute("UPDATE settings SET value=? WHERE key='admin_password'", (sha(p1),))
            st.success("비밀번호 변경 완료")
