"""Causal local research feature calculations (version 3)."""

import numpy as np
import pandas as pd
from data_collectors.trading_calendar import reindex_to_krx_trading_days


def generate_full_alpha158_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    alpha158 팩터 생성 (수식 완전 벡터화 버전)
    """
    df = df.copy()

    open_p = df["Open"]
    high_p = df["High"]
    low_p = df["Low"]
    close_p = df["Close"]
    vol = df["Volume"]
    if "VWAP" not in df.columns:
        raise ValueError("실제 VWAP 컬럼이 필요합니다.")
    # 거래대금/거래량으로 계산하고 수정주가 배율을 적용한 실제 일별 VWAP
    vwap = df["VWAP"]
    epsilon = 1e-8

    # --- 1. KBAR Features (캔들 형태) ---
    # KMID: 시가 대비 종가 수익률. 양수일수록 장중 매수 우위
    df["kmid"] = (close_p - open_p) / (open_p + epsilon)
    # KLEN: 시가 대비 고저 변동폭. 클수록 장중 변동성이 큼
    df["klen"] = (high_p - low_p) / (open_p + epsilon)
    # KMID2: 전체 고저폭 중 시가→종가 이동 비율. 부호는 캔들 방향을 표시
    df["kmid_2"] = (close_p - open_p) / (high_p - low_p + epsilon)
    # KUP: 시가 대비 윗꼬리 길이. 클수록 고가에서 밀린 폭이 큼
    df["kup"] = (high_p - np.maximum(open_p, close_p)) / (open_p + epsilon)
    # KUP2: 전체 고저폭 중 윗꼬리 비중. 상단 가격 거부 강도를 표시
    df["kup_2"] = (high_p - np.maximum(open_p, close_p)) / (high_p - low_p + epsilon)
    # KLOW: 시가 대비 아랫꼬리 길이. 클수록 저가에서 회복한 폭이 큼
    df["klow"] = (np.minimum(open_p, close_p) - low_p) / (open_p + epsilon)
    # KLOW2: 전체 고저폭 중 아랫꼬리 비중. 하단 매수 반응 강도를 표시
    df["klow_2"] = (np.minimum(open_p, close_p) - low_p) / (high_p - low_p + epsilon)
    # KSFT: 시가 대비 종가의 고저 중간값 이탈. 양수면 종가가 범위 상단에 가까움
    df["ksft"] = (2 * close_p - high_p - low_p) / (open_p + epsilon)
    # KSFT2: 고저폭으로 정규화한 종가 위치. 종목 가격 수준과 무관한 장중 강도
    df["ksft_2"] = (2 * close_p - high_p - low_p) / (high_p - low_p + epsilon)

    # --- 2. 기본 비율 ---
    # OPEN0: 종가 대비 시가. 1보다 작으면 종가가 시가보다 높음
    df["open_0"] = open_p / (close_p + epsilon)
    # HIGH0: 종가 대비 고가. 1과의 차이가 종가 위쪽 되돌림 폭
    df["high_0"] = high_p / (close_p + epsilon)
    # LOW0: 종가 대비 저가. 1과의 차이가 저가에서 종가까지의 회복 폭
    df["low_0"] = low_p / (close_p + epsilon)
    # VWAP0: 종가 대비 실제 일별 VWAP. 1 미만이면 종가가 평균 체결가보다 높음
    df["vwap_0"] = vwap / (close_p + epsilon)

    # 가격 방향·절대 이동량 캐시: CN*/SUM* 계열에서 상승·하락 지속성을 계산
    is_up = (close_p > close_p.shift(1)).astype(float)
    is_down = (close_p < close_p.shift(1)).astype(float)
    up_move = (close_p - close_p.shift(1)).clip(lower=0)
    down_move = (close_p.shift(1) - close_p).clip(lower=0)
    tot_move = up_move + down_move

    # 거래량 방향·절대 변화량 캐시: VSUM* 계열에서 수급 증가·감소 강도를 계산
    v_up_move = (vol - vol.shift(1)).clip(lower=0)
    v_down_move = (vol.shift(1) - vol).clip(lower=0)
    v_tot_move = v_up_move + v_down_move

    # 일별 가격·거래량 변화율 캐시: CORD에서 두 변화의 동행성을 계산
    ret = close_p / (close_p.shift(1) + epsilon) - 1.0
    v_ret = vol / (vol.shift(1) + epsilon) - 1.0

    # --- 3. W일 Window 기반 피처 (5, 10, 20, 30, 60) ---
    windows = [5, 10, 20, 30, 60]
    new_cols = {}

    for w in windows:
        # ROC: 현재 종가 대비 W일 전 종가. 1 미만이면 그 기간 가격이 상승
        new_cols[f"roc_{w}"] = close_p.shift(w) / (close_p + epsilon)
        # MA: 현재 종가 대비 W일 평균 종가. 1 미만이면 현재가가 평균 위에 위치
        new_cols[f"ma_{w}"] = close_p.rolling(w).mean() / (close_p + epsilon)
        # MAX: 현재 종가 대비 W일 최고가. 최근 고점까지 남은 거리를 표시
        new_cols[f"max_{w}"] = high_p.rolling(w).max() / (close_p + epsilon)
        # MIN: 현재 종가 대비 W일 최저가. 최근 저점 대비 현재 위치를 표시
        new_cols[f"min_{w}"] = low_p.rolling(w).min() / (close_p + epsilon)

        roll_max = high_p.rolling(w).max()
        roll_min = low_p.rolling(w).min()
        # RSV: W일 고저 범위 내 현재 종가 위치. 1에 가까울수록 최근 상단
        new_cols[f"rsv_{w}"] = (close_p - roll_min) / (roll_max - roll_min + epsilon)

        # STD: 현재 종가로 정규화한 W일 종가 표준편차. 클수록 변동성이 큼
        new_cols[f"std_{w}"] = close_p.rolling(w).std() / (close_p + epsilon)

        # 회귀 공통값: W일 가격 추세선의 기울기·적합도·잔차를 벡터화해 계산
        mean_x = (w - 1) / 2.0
        x_var = (w**2 - 1) / 12.0

        sum_y = close_p.rolling(w).sum()
        mean_y = sum_y / w
        y_var = close_p.rolling(w).var(ddof=0)

        sum_xy = sum(i * close_p.shift(w - 1 - i) for i in range(w))
        mean_xy = sum_xy / w
        cov_xy = mean_xy - mean_x * mean_y

        # BETA: W일 종가 회귀선의 일 단위 기울기. 양수일수록 상승 추세
        new_cols[f"beta_{w}"] = cov_xy / x_var
        # RSQR: 시간 추세가 종가 변동을 설명하는 비율. 1에 가까울수록 추세가 선명
        new_cols[f"rsqr_{w}"] = (new_cols[f"beta_{w}"] ** 2) * x_var / (y_var + epsilon)

        pred_y = mean_y + new_cols[f"beta_{w}"] * mean_x
        # RESI: 추세선 예상 종가 대비 현재 종가 잔차. 양수면 추세선보다 위
        new_cols[f"resi_{w}"] = (close_p - pred_y) / (close_p + epsilon)

        # RANK: W일 종가 중 현재 종가의 상대 순위. 1에 가까울수록 기간 고점권
        new_cols[f"rank_{w}"] = sum((close_p >= close_p.shift(i)).astype(int) for i in range(w)) / w
        # QTLU: 현재 종가 대비 W일 종가 80% 분위값. 상단 가격대와의 거리
        new_cols[f"qtlu_{w}"] = close_p.rolling(w).quantile(0.8) / (close_p + epsilon)
        # QTLD: 현재 종가 대비 W일 종가 20% 분위값. 하단 가격대와의 거리
        new_cols[f"qtld_{w}"] = close_p.rolling(w).quantile(0.2) / (close_p + epsilon)

        # 극값 위치 탐색: 0은 윈도우 시작, W-1은 가장 최근 거래일
        imax_idx = pd.Series(-1, index=df.index)
        imin_idx = pd.Series(-1, index=df.index)

        for k in range(w):
            shift_amt = w - 1 - k
            is_max = high_p.shift(shift_amt) == roll_max
            is_min = low_p.shift(shift_amt) == roll_min

            imax_idx = np.where((imax_idx == -1) & is_max, k, imax_idx)
            imin_idx = np.where((imin_idx == -1) & is_min, k, imin_idx)

        # IMAX: W일 최고가 발생 시점. 클수록 최고가가 최근에 형성됨
        new_cols[f"imax_{w}"] = imax_idx / w
        # IMIN: W일 최저가 발생 시점. 클수록 최저가가 최근에 형성됨
        new_cols[f"imin_{w}"] = imin_idx / w
        # IMXD: 최고가와 최저가 시점 차이. 양수면 저점 뒤 고점이 형성된 구조
        new_cols[f"imxd_{w}"] = new_cols[f"imax_{w}"] - new_cols[f"imin_{w}"]

        cntp = is_up.rolling(w).mean()
        cntn = is_down.rolling(w).mean()
        # CNTP: W일 중 전일 대비 상승한 날의 비율. 상승 빈도를 측정
        new_cols[f"cntp_{w}"] = cntp
        # CNTN: W일 중 전일 대비 하락한 날의 비율. 하락 빈도를 측정
        new_cols[f"cntn_{w}"] = cntn
        # CNTD: 상승일 비율과 하락일 비율의 차이. 양수면 상승일이 우세
        new_cols[f"cntd_{w}"] = cntp - cntn

        sump = up_move.rolling(w).sum() / (tot_move.rolling(w).sum() + epsilon)
        sumn = down_move.rolling(w).sum() / (tot_move.rolling(w).sum() + epsilon)
        # SUMP: W일 절대 가격 이동 중 상승 이동이 차지한 비중
        new_cols[f"sump_{w}"] = sump
        # SUMN: W일 절대 가격 이동 중 하락 이동이 차지한 비중
        new_cols[f"sumn_{w}"] = sumn
        # SUMD: 상승 이동 비중과 하락 이동 비중의 차이. 가격 방향 에너지
        new_cols[f"sumd_{w}"] = sump - sumn

        # CORR: W일 종가 수준과 거래량 수준의 상관. 가격·활동량 동행 여부
        new_cols[f"corr_{w}"] = close_p.rolling(w).corr(vol)
        # CORD: W일 가격 수익률과 거래량 변화율의 상관. 변동 시 거래량 반응
        new_cols[f"cord_{w}"] = ret.rolling(w).corr(v_ret)

        # VMA: 현재 거래량 대비 W일 평균 거래량. 1 미만이면 현재 거래량이 평균 이상
        new_cols[f"vma_{w}"] = vol.rolling(w).mean() / (vol + epsilon)
        # VSTD: 현재 거래량으로 정규화한 W일 거래량 표준편차
        new_cols[f"vstd_{w}"] = vol.rolling(w).std() / (vol + epsilon)

        wvma = (vol * (high_p - low_p) / (open_p + epsilon)).rolling(w).mean()
        # WVMA: 거래량으로 가중한 장중 변동폭의 W일 평균을 현재 거래량으로 정규화
        new_cols[f"wvma_{w}"] = wvma / (vol + epsilon)

        vsump = v_up_move.rolling(w).sum() / (v_tot_move.rolling(w).sum() + epsilon)
        vsumn = v_down_move.rolling(w).sum() / (v_tot_move.rolling(w).sum() + epsilon)
        # VSUMP: W일 절대 거래량 변화 중 증가분이 차지한 비중
        new_cols[f"vsump_{w}"] = vsump
        # VSUMN: W일 절대 거래량 변화 중 감소분이 차지한 비중
        new_cols[f"vsumn_{w}"] = vsumn
        # VSUMD: 거래량 증가 비중과 감소 비중의 차이. 수급 활동 방향성
        new_cols[f"vsumd_{w}"] = vsump - vsumn

    df = pd.concat([df, pd.DataFrame(new_cols, index=df.index)], axis=1)
    return df


def normalize_trading_halts(df, trading_days):
    """Normalize unavailable session bars for features, retaining raw turnover."""
    original = df.copy()
    dates = pd.to_datetime(original.Date).dt.normalize()
    if dates.duplicated().any():
        raise ValueError("Duplicate source dates")
    indexed = reindex_to_krx_trading_days(original, trading_days)
    missing = indexed.index.difference(pd.DatetimeIndex(dates))
    if len(missing):
        raise ValueError(f"Unverified missing sessions: {missing[:5].tolist()}")
    halt = indexed.get("Trading_Halt", pd.Series(False, index=indexed.index)).eq(
        1
    ) | indexed.Volume.eq(0)
    # This excludes a missing regular-session bar without claiming an official
    # suspension. Trading_Halt is the downstream execution exclusion flag.
    unavailable = indexed.get("RegularSessionUnavailable", pd.Series(False, index=indexed.index)).eq(1)
    halt |= unavailable
    if indexed.Volume.isna().any() or indexed.Volume.lt(0).any():
        raise ValueError("Missing or negative Volume")
    traded = ~halt
    cols = ["Open", "High", "Low", "Close", "VWAP"]
    values = indexed.loc[traded, cols].to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values <= 0).any():
        raise ValueError("Traded rows require positive finite OHLC/VWAP")
    indexed["Trading_Halt"] = halt.astype("int8")
    indexed.loc[halt, "Close"] = indexed.loc[halt, "Close"].where(indexed.loc[halt, "Close"] > 0)
    indexed["Close"] = indexed.Close.ffill()
    if indexed.Close.isna().any():
        raise ValueError("Halt has no confirmed preceding price")
    for col in ["Open", "High", "Low", "VWAP"]:
        indexed.loc[halt, col] = indexed.loc[halt, "Close"]
    indexed.loc[halt, "Volume"] = 0
    return indexed.reset_index()


def build_feature_frame(raw, trading_days, settings):
    frame = generate_full_alpha158_features(normalize_trading_halts(raw, trading_days))
    frame["Log_Ret"] = np.log(frame.Close / frame.Close.shift(1))
    halt = frame.Trading_Halt.eq(1)
    frame.loc[halt, "Log_Ret"] = 0.0
    frame["Sigma"] = (
        frame.Log_Ret.where(~halt)
        .rolling(settings["sigma_window"], min_periods=settings["sigma_min_periods"])
        .std()
    )
    frame["Barrier_Up"] = frame.Close * (1 + settings["barrier_feature_up_mult"] * frame.Sigma)
    frame["Barrier_Down"] = frame.Close * (1 - settings["barrier_feature_down_mult"] * frame.Sigma)
    if "Change" not in frame:
        frame["Change"] = frame.Close.pct_change(fill_method=None) * 100
    frame = frame.drop(columns=["Y_Label", "y_label"], errors="ignore")
    numeric = frame.select_dtypes(include="number").columns
    frame[numeric] = frame[numeric].replace([np.inf, -np.inf], np.nan)
    return frame
