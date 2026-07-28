# 유역안심 AI (Streamlit)

프로토타입(HTML)과 동일한 로직(계절 백분위, 표층/근권 비교, 7일 추세 예측, Claude API 요약)을
실제 배포 가능한 Streamlit 앱으로 옮긴 버전입니다.

## 로컬에서 실행해보기

```bash
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# secrets.toml 안의 ANTHROPIC_API_KEY 값을 실제 키로 교체
streamlit run app.py
```

## Streamlit Community Cloud로 배포하기

1. 이 폴더를 GitHub 저장소에 올리기 (`.streamlit/secrets.toml`은 `.gitignore`에 포함되어 있어
   실수로 올라가지 않습니다 — `secrets.toml.example`만 커밋하세요)
2. [share.streamlit.io](https://share.streamlit.io) → GitHub 계정으로 로그인 → New app
3. 저장소 선택, Main file path에 `app.py` 입력 → Deploy
4. 배포 후 **App settings → Secrets**에 등록:
   ```toml
   ANTHROPIC_API_KEY = "sk-ant-실제키"
   ```
5. 발급된 `*.streamlit.app` 주소가 실제 서비스 URL입니다.

## 데이터 갱신하기

`data/` 폴더 안의 xlsx 파일(surface·rootzone 시트 포함)을 최신 파일로 교체하면 됩니다.
앱은 폴더 안에서 파일명 기준 가장 마지막 파일을 자동으로 사용합니다.

⚠️ **알려진 데이터 품질 이슈**: 현재 원본 파일은 날짜 항목이 12월까지 있으나 실제 값은
850개 유역 전체가 특정 시점 이후 결측 상태입니다. 앱은 값이 존재하는 마지막 날짜를 자동으로
찾아 기준일로 표시하며, 최신 데이터 확보 시 자동으로 갱신됩니다. (기관에 갱신주기 문의 필요)

## 파일 구조

```
app.py                 # Streamlit UI 메인 (3개 탭: 현황/AI예측/순위)
data_processing.py      # 통계·백테스트 로직 (프로토타입과 동일 검증된 로직)
data/*.xlsx              # 원본 데이터 (surface/rootzone 시트)
requirements.txt
.streamlit/secrets.toml.example
```
