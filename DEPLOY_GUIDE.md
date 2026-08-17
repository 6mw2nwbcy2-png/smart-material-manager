# Smart Material Manager v1.1 - 인터넷 배포 가이드

## 권장 구조
- 화면/앱 서버: Streamlit Community Cloud
- 중앙 데이터베이스: Supabase PostgreSQL
- 소스 보관: GitHub 비공개 저장소 권장

이 구조로 배포하면 현장 직원 PC나 휴대폰에 Python을 설치할 필요가 없습니다.
직원은 배포된 `https://...streamlit.app` 주소만 브라우저로 열면 됩니다.

## 1. Supabase에서 중앙 DB 만들기
1. Supabase 프로젝트를 생성합니다.
2. 프로젝트 Dashboard의 **Connect** 메뉴에서 PostgreSQL 연결 문자열을 복사합니다.
3. Streamlit 같은 외부 호스팅 환경에서 IPv6 문제가 있으면 Supabase의 Session pooler 연결 문자열을 사용하세요.
4. 비밀번호가 들어 있는 DATABASE_URL은 메신저나 GitHub 코드에 직접 적지 마세요.

앱은 최초 실행 시 필요한 테이블을 자동 생성합니다.

## 2. GitHub에 코드 올리기
이 폴더의 파일을 하나의 GitHub 저장소에 올립니다.
권장: 회사 데이터가 들어가므로 Private repository.

필수 파일:
- app.py
- requirements.txt
- .streamlit/config.toml
- .gitignore

주의:
- 실제 DATABASE_URL이 들어간 `.streamlit/secrets.toml`은 GitHub에 올리지 않습니다.

## 3. Streamlit Community Cloud에 배포
1. Streamlit Community Cloud 로그인
2. GitHub 계정 연결
3. Create app
4. Repository 선택
5. Main file path: `app.py`
6. Advanced settings / Secrets에 아래와 같이 입력

DATABASE_URL = "Supabase에서 복사한 PostgreSQL 연결 문자열"

7. Deploy

배포되면 `https://원하는주소.streamlit.app` 형태의 주소가 생깁니다.

## 4. 현장 직원 사용
- PC: Edge/Chrome에서 URL 접속
- 휴대폰: 같은 URL 접속
- Python 설치 불필요
- 집/회사/모바일망 등 인터넷만 연결되면 접속 가능
- 모든 사용자가 같은 중앙 DB를 봅니다.

## 권한
일반 사용자:
- 자재 현황 조회
- 철근/레미콘/타일 투입 입력
- 타일 발주서 작성 및 PDF 다운로드

관리자:
- 위 기능 전체
- 품목 추가/수정
- 예산수량 변경
- 발주/입고 수정
- 발주 완료 및 결재 상태 관리

## 중요 보안 사항
이 앱에는 회사 공사 자재 데이터가 들어갈 수 있으므로 실제 외부 배포 전 회사의 정보보안/클라우드 사용 정책을 확인하는 것을 권장합니다.
현재 v1.1 관리자 인증은 간단한 비밀번호 방식입니다. 전사/대규모 운영 전에는 Microsoft Entra ID 등 회사 계정 로그인 연동을 권장합니다.
