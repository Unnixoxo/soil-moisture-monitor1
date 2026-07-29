"""
유역안심 AI (Streamlit)
데이터: 한국수자원조사기술원 「주요 유역별 토양수분량 자료」(표층/근권, 850개 표준유역)

배포: Streamlit Community Cloud
- ANTHROPIC_API_KEY 는 st.secrets 로 관리 (코드에 절대 하드코딩하지 않음)
"""

import os
import glob
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from data_processing import (
    FORECAST_DAYS,
    LEVELS,
    build_korea_svg,
    build_ranking_html,
    chart_series,
    compute_stats,
    load_surface_rootzone,
    region_summary,
    true_last_valid_date,
)

st.set_page_config(page_title="유역안심 AI", page_icon="💧", layout="wide")

LEVEL_COLOR = {"정상": "#3b82f6", "관심": "#84cc16", "주의": "#eab308", "경계": "#f97316", "심각": "#dc2626"}
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")


# ── 데이터 로드 & 계산 (캐시) ──────────────────────────────────
@st.cache_data(show_spinner="데이터를 불러오는 중...")
def get_data():
    files = sorted(glob.glob(os.path.join(DATA_DIR, "*.xlsx")))
    if not files:
        return None, None, None, None
    surface, rootzone = load_surface_rootzone(files[-1])  # 가장 최근 파일 사용
    as_of = true_last_valid_date(surface)
    stats = compute_stats(surface, rootzone, as_of)
    return surface, rootzone, stats, as_of


surface, rootzone, stats, as_of = get_data()

st.title("💧 유역안심 AI")
if stats is None:
    st.error(
        "data/ 폴더에 xlsx 파일이 없습니다. 한국수자원조사기술원 「주요 유역별 토양수분량 자료」"
        "(surface/rootzone 시트 포함)를 data/ 폴더에 넣어주세요."
    )
    st.stop()

if as_of < surface["TIME"].max():
    st.warning(
        f"⚠ 데이터 품질 참고: 원본 파일의 날짜 항목은 {surface['TIME'].max().date()}까지 있으나, "
        f"실제 값은 {as_of.date()} 이후 결측 상태입니다. 이 화면은 값이 존재하는 마지막 시점을 기준일로 표시합니다.",
        icon="⚠️",
    )

st.caption(f"데이터 기준일 **{as_of.date()}** · 표준유역 **{len(stats)}개** · 표층/근권 실측 기반")

tab1, tab2, tab3 = st.tabs(["토양수분 현황", "AI 위험예측", "유역별 분석"])

# ── 탭 1: 토양수분 현황 ──────────────────────────────────
with tab1:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("전국 평균 표층 토양수분량", f"{stats['surface'].mean():.3f} ㎥/㎥")
    concern = (stats["status"] != "정상").sum()
    c2.metric("관심 이상 유역", f"{concern}개", f"{concern/len(stats)*100:.1f}%")
    high_risk = stats["status"].isin(["경계", "심각"]).sum()
    c3.metric("경계·심각 유역", f"{high_risk}개")
    c4.metric("데이터 기준일", str(as_of.date()))

    st.subheader("권역별 토양수분 현황 (실측)")
    ragg = region_summary(stats)

    region_options = ["(선택 안 함)"] + list(ragg["region"])
    picked = st.selectbox("권역 선택", region_options, key="region_picker")
    clicked_region = picked if picked != "(선택 안 함)" else None

    svg_html = build_korea_svg(ragg, selected_region=clicked_region)
    st.components.v1.html(svg_html, height=560)
    st.caption("원 크기 = 권역 내 유역 수, % = 권역 평균 백분위 (빨강=건조 ~ 파랑=습윤) · 위 드롭다운에서 권역을 선택하면 강조 표시됩니다")

    if clicked_region:
        rrow = ragg[ragg["region"] == clicked_region].iloc[0]
        worst = stats[stats["region"] == clicked_region].sort_values("pct").iloc[0]
        d1, d2, d3, d4 = st.columns(4)
        d1.metric("선택 권역", clicked_region.replace("권역", ""))
        d2.metric("권역 평균 백분위", f"{rrow['avg_pct']}%")
        d3.metric("유역 수", f"{rrow['n']}개")
        d4.metric("가장 건조한 유역", worst["name"])
        wc1, wc2, wc3 = st.columns(3)
        wc1.metric("표층", f"{worst['surface']} ㎥/㎥")
        wc2.metric("백분위", f"하위 {worst['pct']}%")
        wc3.metric("상태", worst["status"])
        if st.button("이 유역으로 AI 위험예측 탭에서 분석하기"):
            st.session_state["jump_to_col"] = worst["col"]
            st.info("상단의 'AI 위험예측' 탭을 클릭해 이어서 확인해주세요.")

    with st.expander("권역별 상세 수치 보기"):
        st.dataframe(
            ragg[["region", "provinces", "n", "avg_pct"]].rename(columns={
                "region": "권역", "provinces": "포함 시도", "n": "유역 수", "avg_pct": "평균 백분위(%)",
            }),
            use_container_width=True, hide_index=True,
        )

# ── 탭 2: AI 위험예측 ──────────────────────────────────
with tab2:
    q = st.text_input("유역 검색 (유역명 또는 권역)", "")
    matches = stats[stats["name"].str.contains(q) | stats["region"].str.contains(q)] if q else stats
    if len(matches) == 0:
        st.info("검색 결과가 없습니다.")
        st.stop()
    default_col = matches.sort_values("pct").iloc[0]["col"]
    options = matches.assign(label=lambda d: d["region"] + " · " + d["name"])
    jump_col = st.session_state.get("jump_to_col")
    if jump_col in options["col"].values:
        default_idx = int(options.reset_index(drop=True).index[options.reset_index(drop=True)["col"] == jump_col][0])
    else:
        default_idx = 0
    selected_label = st.selectbox("분석 대상 유역", options["label"], index=default_idx)
    row = options[options["label"] == selected_label].iloc[0]

    badge_color = LEVEL_COLOR[row["status"]]
    st.markdown(f"### {row['region']} {row['name']}  <span style='color:{badge_color}'>● {row['status']}</span>", unsafe_allow_html=True)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("표층 토양수분량", f"{row['surface']} ㎥/㎥")
    m2.metric("근권 토양수분량", f"{row['root']} ㎥/㎥" if row["root"] is not None else "-")
    m3.metric("계절 백분위", f"하위 {row['pct']}%")
    m4.metric("7일 후 예측치", f"{row['pred7']} ㎥/㎥")

    # ── AI 분석 결과 (예시 — 실시간 API 아님) ──
    with st.container(border=True):
        st.markdown("#### ℹ️ AI 분석 결과")
        summary = (
            f"{row['region'].replace('권역','')} {row['name']} 유역은 현재 표층 토양수분량 {row['surface']} ㎥/㎥"
            f"(근권 {row['root']} ㎥/㎥)로, 당해 계절 평균 대비 백분위 {row['pct']}% 수준입니다. "
            f"최근 14일간 {row['trend_word']} 추세를 보이고 있으며, 위험 단계는 '{row['status']}'입니다."
        )
        st.write(summary)
        st.caption("위 문단은 실제 유역 데이터를 근거로 미리 구성한 예시입니다. 아래 버튼을 누르면 Claude API로 실시간 생성합니다.")

        if st.button("🤖 Claude로 실시간 분석 생성", type="primary"):
            api_key = st.secrets.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
            if not api_key:
                st.error("ANTHROPIC_API_KEY가 설정되지 않았습니다. Streamlit Cloud의 App settings → Secrets에 등록해주세요.")
            else:
                with st.spinner("분석 생성 중..."):
                    try:
                        import anthropic
                        client = anthropic.Anthropic(api_key=api_key)
                        prompt = f"""당신은 공공기관의 수자원 데이터 분석 담당자입니다. 다음 유역 데이터를 바탕으로,
아래 7단계 절차에 따라 짧은 소견과 종합 분석 문단(2~3문장)을 작성하세요. 과장 없이 담백한 보고서체로 작성하세요.

유역명: {row['region']} {row['name']}
표층 토양수분량: {row['surface']} ㎥/㎥
근권 토양수분량: {row['root']} ㎥/㎥
계절 백분위: 하위 {row['pct']}%
Z-score: {row['z']}
최근 14일 추세: {row['trend_word']}
7일 후 예측치: {row['pred7']} ㎥/㎥
위험 단계: {row['status']}

[분석 절차] 1.자료수집 2.데이터통합 3.이상값점검 4.패턴분석 5.예측 6.위험등급산출 7.영향요인설명"""
                        resp = client.messages.create(
                            model="claude-sonnet-4-6", max_tokens=400,
                            messages=[{"role": "user", "content": prompt}],
                        )
                        text = "".join(b.text for b in resp.content if hasattr(b, "text"))
                        st.markdown(text)
                    except Exception as e:
                        st.error(f"생성 중 오류: {e}")

    # ── 추이 차트 (표층/근권 실측 + 7일 예측) ──
    s_series, r_series = chart_series(surface, rootzone, row["col"], as_of)
    fig2 = go.Figure()
    fig2.add_trace(go.Scatter(x=s_series["TIME"], y=s_series["value"], mode="lines", name="표층(실측)", line=dict(color="#0f766e", width=2.5)))
    fig2.add_trace(go.Scatter(x=r_series["TIME"], y=r_series["value"], mode="lines", name="근권(실측)", line=dict(color="#7c3aed", width=2, dash="dash")))

    last_actual = s_series["value"].iloc[-1]
    future_dates = pd.date_range(as_of + pd.Timedelta(days=1), periods=FORECAST_DAYS)
    forecast_vals = [last_actual + (row["pred7"] - last_actual) * (i + 1) / FORECAST_DAYS for i in range(FORECAST_DAYS)]
    fig2.add_trace(go.Scatter(
        x=[as_of] + list(future_dates), y=[last_actual] + forecast_vals,
        mode="lines", name="7일 예측(추세 연장)", line=dict(color="#dc2626", width=2, dash="dot"),
    ))
    fig2.update_layout(height=320, margin=dict(l=10, r=10, t=30, b=10), yaxis_title="㎥/㎥",
                        legend=dict(orientation="h", yanchor="bottom", y=1.02))
    st.plotly_chart(fig2, use_container_width=True)
    st.caption("빨간 점선은 최근 14일 추세를 단순 연장한 참고용 예측입니다 (검증된 예측 모델 아님).")

# ── 탭 3: 유역별 분석 (순위) ──────────────────────────────────
with tab3:
    st.subheader("AI가 선정한 관리 필요 유역 순위")
    st.caption(f"{as_of.date()} 시점 · 백분위가 낮을수록(건조할수록) 상위 순위")

    c1, c2, c3 = st.columns([2, 1, 1])
    with c1:
        query = st.text_input("유역명 또는 권역 검색", key="tab3_search")
    with c2:
        risk_filter = st.selectbox("위험 단계", ["전체"] + LEVELS)
    with c3:
        sort_metric = st.selectbox("정렬 기준", ["백분위", "추세(기울기)", "표층값"])

    view = stats.copy()
    if query:
        view = view[view["name"].str.contains(query) | view["region"].str.contains(query)]
    if risk_filter != "전체":
        view = view[view["status"] == risk_filter]
    sort_col = {"백분위": "pct", "추세(기울기)": "slope14", "표층값": "surface"}[sort_metric]
    view = view.sort_values(sort_col).reset_index(drop=True)
    view.insert(0, "순위", view.index + 1)

    st.caption(f"{len(view)}개 유역 중 순위 표시")
    st.components.v1.html(build_ranking_html(view), height=560, scrolling=True)

st.divider()
st.caption(
    "데이터 제공: 한국수자원조사기술원 · 활용 데이터: 주요 유역별 토양수분량 자료(표층·근권) · "
    "AI 분석은 실제 데이터를 근거로 생성되며, 예측·위험등급은 자체 통계 로직 기반 참고용입니다."
)
