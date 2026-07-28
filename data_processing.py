"""
유역안심 AI - 데이터 처리 모듈
한국수자원조사기술원 「주요 유역별 토양수분량 자료」(표층/근권) 처리 로직.
프로토타입(HTML)에서 검증한 것과 동일한 계산 방식입니다.
"""

import json
import os

import numpy as np
import pandas as pd

N_DAYS = 366
CLIM_WINDOW = 10          # 계절 기후값 계산 시 ±N일 순환 평균 (1년치 데이터라 넓게 잡음)
TREND_DAYS = 14             # 추세 계산에 사용하는 최근 일수
FORECAST_DAYS = 7           # 추세 연장 예측 일수

LEVELS = ["정상", "관심", "주의", "경계", "심각"]

# 6개 대권역의 실제 지리적 대표 위경도(주요 본류 중심부, 근사치) — 지도 시각화용
REGION_LATLON = {
    "한강권역": (37.35, 127.55),
    "낙동강권역": (36.05, 128.35),
    "금강권역": (36.30, 127.20),
    "섬진강권역": (35.20, 127.45),
    "영산강권역": (35.00, 126.70),
    "제주도": (33.38, 126.55),
}
REGION_PROVINCES = {
    "한강권역": "서울·경기·강원",
    "낙동강권역": "부산·대구·울산·경북·경남",
    "금강권역": "대전·세종·충북·충남",
    "섬진강권역": "전북·전남 동부·경남 서부",
    "영산강권역": "광주·전남",
    "제주도": "제주",
}


def load_surface_rootzone(path: str):
    """xlsx 파일에서 surface/rootzone 시트를 읽어 정리합니다."""
    surface = pd.read_excel(path, sheet_name="surface", engine="openpyxl")
    rootzone = pd.read_excel(path, sheet_name="rootzone", engine="openpyxl")
    surface = surface.dropna(subset=["TIME"]).reset_index(drop=True)
    rootzone = rootzone.dropna(subset=["TIME"]).reset_index(drop=True)
    surface["TIME"] = pd.to_datetime(surface["TIME"])
    rootzone["TIME"] = pd.to_datetime(rootzone["TIME"])
    return surface, rootzone


def true_last_valid_date(surface: pd.DataFrame) -> pd.Timestamp:
    """실제 값이 존재하는 마지막 날짜를 찾습니다 (날짜 칸과 실제값 범위가 다를 수 있음)."""
    cols = [c for c in surface.columns if c not in ("TIME", "doy")]
    last_valid_idx = surface[cols].apply(lambda s: s.last_valid_index())
    valid_positions = last_valid_idx.dropna().astype(int)
    if len(valid_positions) == 0:
        return surface["TIME"].max()
    return surface["TIME"].iloc[valid_positions].max()


def _circular_clim(doy_arr: np.ndarray, val_arr: np.ndarray) -> np.ndarray:
    clim = np.full(N_DAYS + 1, np.nan)
    for target in range(1, N_DAYS + 1):
        diff = np.abs(doy_arr - target)
        diff = np.minimum(diff, N_DAYS - diff)
        mask = diff <= CLIM_WINDOW
        if mask.sum() > 0:
            clim[target] = val_arr[mask].mean()
    return clim


def _classify(pct: float) -> str:
    if pct <= 10: return "심각"
    if pct <= 25: return "경계"
    if pct <= 45: return "주의"
    if pct <= 70: return "관심"
    return "정상"


def _trend_word(slope: float) -> str:
    if slope <= -0.0015: return "지속 감소"
    if slope <= -0.0004: return "완만한 감소"
    if slope >= 0.0015: return "지속 증가"
    if slope >= 0.0004: return "완만한 증가"
    return "안정"


def compute_stats(surface: pd.DataFrame, rootzone: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
    """유역별 최신값 / 계절 백분위 / 추세 / 7일 예측치를 계산합니다."""
    surface = surface[surface["TIME"] <= as_of].copy()
    rootzone = rootzone[rootzone["TIME"] <= as_of].copy()
    surface["doy"] = surface["TIME"].dt.dayofyear
    rootzone["doy"] = rootzone["TIME"].dt.dayofyear
    cols = [c for c in surface.columns if c not in ("TIME", "doy")]

    rows = []
    for col in cols:
        s = surface[["TIME", "doy", col]].dropna()
        r = rootzone[["TIME", "doy", col]].dropna() if col in rootzone.columns else None
        if len(s) < 30:
            continue

        doy_arr = s["doy"].values.astype(int)
        val_arr = s[col].values.astype(float)
        clim = _circular_clim(doy_arr, val_arr)

        latest_val = float(s[col].iloc[-1])
        latest_doy = int(s["doy"].iloc[-1])

        diff = np.abs(doy_arr - latest_doy)
        diff = np.minimum(diff, N_DAYS - diff)
        pool = val_arr[diff <= 30]
        if len(pool) < 15:
            pool = val_arr
        pct = float((pool < latest_val).mean() * 100)
        std_pool = pool.std()
        z = float((latest_val - pool.mean()) / std_pool) if std_pool > 0 else 0.0

        last_n = s.tail(TREND_DAYS)
        slope = float(np.polyfit(range(len(last_n)), last_n[col].values, 1)[0]) if len(last_n) >= 2 else 0.0
        root_val = float(r[col].iloc[-1]) if r is not None and len(r) > 0 else None

        status = _classify(pct)
        pred = float(np.clip(latest_val + slope * FORECAST_DAYS * 0.6, 0, 0.6))

        region = col.split("_")[0] if "_" in col else "기타"
        name = col.split("_", 1)[1].split("(")[0] if "_" in col else col

        rows.append({
            "col": col, "region": region, "name": name,
            "surface": round(latest_val, 4),
            "root": round(root_val, 4) if root_val is not None else None,
            "pct": round(pct, 1), "z": round(z, 2), "slope14": round(slope, 5),
            "trend_word": _trend_word(slope), "status": status,
            "risk_up": slope < -0.0003, "pred7": round(pred, 4),
        })

    return pd.DataFrame(rows)


def region_summary(stats: pd.DataFrame) -> pd.DataFrame:
    agg = stats.groupby("region").agg(n=("col", "count"), avg_pct=("pct", "mean")).reset_index()
    agg["avg_pct"] = agg["avg_pct"].round(1)
    agg["lat"] = agg["region"].map(lambda r: REGION_LATLON.get(r, (36.5, 127.8))[0])
    agg["lon"] = agg["region"].map(lambda r: REGION_LATLON.get(r, (36.5, 127.8))[1])
    agg["provinces"] = agg["region"].map(lambda r: REGION_PROVINCES.get(r, ""))
    return agg


_LEVEL_HEX = {"정상": "#3b82f6", "관심": "#84cc16", "주의": "#eab308", "경계": "#f97316", "심각": "#dc2626"}
_ASSET_DIR = os.path.dirname(__file__)


def _load_json(name):
    with open(os.path.join(_ASSET_DIR, name), encoding="utf-8") as f:
        return json.load(f)


def build_korea_svg(region_agg: pd.DataFrame, selected_region: str | None = None) -> str:
    """실제 대한민국 행정구역 SVG(오픈소스) 위에 권역별 원을 그려 넣습니다.
    원 위치는 위경도 기반 아핀 변환으로 계산된 실제 지리 좌표입니다."""
    province_paths = _load_json("korea_province_paths.json")
    positions = _load_json("region_positions.json")

    province_svg = "".join(f'<path d="{d}" fill="#eef1f0" stroke="#fff" stroke-width="1.2"/>' for d in province_paths)

    markers = []
    for _, row in region_agg.iterrows():
        name = row["region"]
        if name not in positions:
            continue
        x, y = positions[name]
        pct = row["avg_pct"]
        status = _classify(pct)
        color = _LEVEL_HEX[status]
        n = row["n"]
        r = 20 + (n ** 0.5) * 0.6
        active = name == selected_region
        if active:
            r = 28
        stroke_w = 3 if active else 2
        markers.append(f'''
          <circle cx="{x}" cy="{y}" r="{r}" fill="{color}" opacity="{1 if active else 0.85}" stroke="#fff" stroke-width="{stroke_w}"/>
          <text x="{x}" y="{y-30}" text-anchor="middle" font-size="15" font-weight="700" fill="#1e293b" font-family="sans-serif">{name.replace('권역','')}</text>
          <text x="{x}" y="{y-16}" text-anchor="middle" font-size="10" font-weight="500" fill="#64748b" font-family="sans-serif">({REGION_PROVINCES.get(name,'')})</text>
          <text x="{x}" y="{y+5}" text-anchor="middle" font-size="12" font-weight="700" fill="#fff" font-family="sans-serif">{pct}%</text>
        ''')

    svg = f'''
    <div style="display:flex; justify-content:center; background:#fff;">
    <svg viewBox="0 0 524 631" style="width:100%; max-width:460px;">
      {province_svg}
      {''.join(markers)}
    </svg>
    </div>
    '''
    return svg
def chart_series(surface: pd.DataFrame, rootzone: pd.DataFrame, col: str, as_of: pd.Timestamp, days: int = 60):
    s = surface[surface["TIME"] <= as_of][["TIME", col]].tail(days)
    r = rootzone[rootzone["TIME"] <= as_of][["TIME", col]].tail(days)
    return s.rename(columns={col: "value"}), r.rename(columns={col: "value"})
