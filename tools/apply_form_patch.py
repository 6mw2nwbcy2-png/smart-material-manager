from pathlib import Path
import shutil
import subprocess

p = Path('app.py')
if not p.exists():
    raise SystemExit('ERROR: app.py not found')

src = p.read_text(encoding='utf-8')
backup = p.with_name('app.py.before_form_patch.bak')
if not backup.exists():
    shutil.copy2(p, backup)

# 1) 관리자 공종에 석재 추가
old = 'options=["철근","레미콘","타일"]'
new = 'options=["철근","레미콘","타일","석재"]'
if src.count(old) != 1:
    raise SystemExit(f'ERROR: admin category option pattern count={src.count(old)}')
src = src.replace(old, new, 1)

# Utility: wrap an exact source range in a form by indenting its body.
def wrap_between(text, start_marker, end_marker, form_key):
    start = text.find(start_marker)
    if start < 0:
        raise SystemExit(f'ERROR: start marker not found: {start_marker}')
    end = text.find(end_marker, start)
    if end < 0:
        raise SystemExit(f'ERROR: end marker not found: {end_marker}')
    block = text[start:end]
    if f'st.form("{form_key}")' in block:
        return text
    lines = block.splitlines(True)
    indented = ''.join(('    ' + line if line.strip() else line) for line in lines)
    # The first marker line remains inside the form too.
    replacement = f'with st.form("{form_key}"):\n' + indented
    return text[:start] + replacement + text[end:]

# 2) 일반 사용자 투입 입력: 입력 중에는 rerun하지 않고 저장 시 한 번에 제출
src = wrap_between(
    src,
    '    st.markdown("### 투입내역 입력")',
    '    if is_admin():',
    'material_use_form'
)
# The original button must be a form submit button.
src = src.replace(
    '    if st.button(f"{cat} 투입 저장", type="primary", key=f"use_save_{cat}"):',
    '    if st.form_submit_button(f"{cat} 투입 저장", type="primary"):',
    1
)

# 3) 관리자 발주/입고 입력: 입력 중에는 rerun하지 않고 저장 시 한 번에 제출
src = wrap_between(
    src,
    '        st.markdown("### 관리자 입력 — 발주 / 입고")',
    '    if cat == "타일":',
    'material_admin_form'
)
src = src.replace(
    '        if st.button("관리자 발주/입고 저장", key=f"adm_save_{cat}"):',
    '        if st.form_submit_button("관리자 발주/입고 저장", type="primary"):',
    1
)

# 4) 타일 발주 전체를 하나의 form으로 묶음. PDF 다운로드는 form 밖에 둔다.
src = wrap_between(
    src,
    '        st.markdown("### 타일 발주서 작성")',
    '            # ---------------- PDF 다운로드 ----------------',
    'tile_order_form'
)
src = src.replace(
    '        if st.button(\n                "선택 품목 일괄 발주 + PDF 생성",\n                type="primary"\n            ):',
    '        if st.form_submit_button(\n                "선택 품목 일괄 발주 + PDF 생성",\n                type="primary"\n            ):',
    1
)

p.write_text(src, encoding='utf-8')

# Syntax check before anything else.
subprocess.run(['python', '-m', 'py_compile', 'app.py'], check=True)
print('PATCH_OK')
print('PYTHON_COMPILE_OK')
print('BACKUP:', backup)
