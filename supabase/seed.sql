-- Kim Minji demo persona seed. Safe to run repeatedly.
-- Requires migrations/0003_ips_profiles_schema_v11.sql (schema_version 1.1.0; style_axes lives in profile_payload).
-- Expected rows on a clean project after execution:
-- users 1 / ips_profiles 1 / avoided_assets 2 / portfolio_holdings 4 /
-- watchlist 3 / stocks 5 / predictions 4 / prediction_features 8 / market_status 1

insert into public.users (id, display_name, avatar_label)
values ('u_minji_001', '김민지', '민')
on conflict (id) do update set
  display_name = excluded.display_name,
  avatar_label = excluded.avatar_label,
  updated_at = now();

insert into public.stocks (code, name, market, risk_grade, risk_flags)
values
  ('005930', '삼성전자', 'KOSPI', 4, '{}'),
  ('035720', '카카오', 'KOSPI', 3, '{}'),
  ('068270', '셀트리온', 'KOSDAQ', 2, array['high_volatility']),
  ('005380', '현대차', 'KOSPI', 5, '{}'),
  ('035420', '네이버', 'KOSPI', 3, '{}'),
  ('247540', '에코프로비엠', 'KOSDAQ', 3, '{}'),
  ('418250', '미래에셋비전스팩3호', 'KOSDAQ', 1, array['spac'])
on conflict (code) do update set
  name = excluded.name,
  market = excluded.market,
  risk_grade = excluded.risk_grade,
  risk_flags = excluded.risk_flags,
  is_active = true,
  updated_at = now();

insert into public.ips_profiles (
  user_id,
  session_id,
  surveyed_at,
  profile_type,
  max_risk_tier,
  risk_score,
  fomo_score,
  horizon_score,
  risk_tolerance,
  time_horizon_months,
  liquidity_need_ratio,
  target_return_annual,
  investment_experience_years,
  fomo_index,
  panic_sell_tendency,
  herding_score,
  self_confidence,
  current_market_anxiety,
  overheating_caution,
  preferred_sectors,
  free_text_raw,
  extracted_signals,
  conflict_with_survey,
  confidence_per_field,
  investment_amount_krw,
  action_intent,
  market_regime_hint,
  benchmark_index,
  schema_version,
  source,
  confidence,
  profile_payload
)
values (
  'u_minji_001',
  's_20260307_001',
  '2026-03-07T14:32:00+09:00',
  'stable',
  4,
  -- risk_score·fomo_score·horizon_score는 화면 3축(8축 묶음 요약)과 같은 값: 위험 감수·흔들림 민감도·투자 기간
  33,
  65,
  38,
  0.35,
  48,
  0.25,
  0.08,
  1.0,
  0.72,
  0.65,
  0.58,
  0.30,
  0.5,
  0.61,
  array['semiconductor', 'healthcare'],
  '남들 다 버는데 나만 뒤처지는 것 같아서 조급해요. 그래도 마이너스 나면 잠을 못 자요.',
  '{"fomo_index": 0.80, "panic_sell_tendency": 0.75}'::jsonb,
  false,
  '{
    "risk_tolerance": 0.92,
    "time_horizon_months": 0.95,
    "liquidity_need_ratio": 0.88,
    "fomo_index": 0.78,
    "panic_sell_tendency": 0.70,
    "herding_score": 0.85,
    "self_confidence": 0.60,
    "overheating_caution": 0.55
  }'::jsonb,
  500000,
  'buy_consideration',
  'high_volatility',
  'KOSPI',
  '1.1.0',
  'profiling_block',
  0.81,
  $profile${
    "user_id": "u_minji_001",
    "session_id": "s_20260307_001",
    "timestamp": "2026-03-07T14:32:00+09:00",
    "investor_profile": {
      "risk_tolerance": 0.35,
      "time_horizon_months": 48,
      "liquidity_need_ratio": 0.25,
      "target_return_annual": 0.08,
      "investment_experience_years": 1.0,
      "profile_type": "stable"
    },
    "psychological_state": {
      "fomo_index": 0.72,
      "panic_sell_tendency": 0.65,
      "herding_score": 0.58,
      "self_confidence": 0.30,
      "current_market_anxiety": 0.5,
      "overheating_caution": 0.61
    },
    "constraints": {
      "avoided_assets": ["spac", "managed_stock"],
      "preferred_sectors": ["semiconductor", "healthcare"]
    },
    "portfolio": {
      "holdings": [
        {"ticker": "005930", "name": "삼성전자", "quantity": 15, "avg_buy_price": 71200},
        {"ticker": "035720", "name": "카카오", "quantity": 8, "avg_buy_price": 48500},
        {"ticker": "068270", "name": "셀트리온", "quantity": 3, "avg_buy_price": 182000},
        {"ticker": "005380", "name": "현대차", "quantity": 5, "avg_buy_price": 235000}
      ],
      "watchlist": ["000660", "035420", "051910"]
    },
    "free_text_signal": {
      "raw_text": "남들 다 버는데 나만 뒤처지는 것 같아서 조급해요. 그래도 마이너스 나면 잠을 못 자요.",
      "extracted_signals": {"fomo_index": 0.80, "panic_sell_tendency": 0.75},
      "conflict_with_survey": false
    },
    "confidence_per_field": {
      "risk_tolerance": 0.92,
      "time_horizon_months": 0.95,
      "liquidity_need_ratio": 0.88,
      "fomo_index": 0.78,
      "panic_sell_tendency": 0.70,
      "herding_score": 0.85,
      "self_confidence": 0.60,
      "overheating_caution": 0.55
    },
    "context": {
      "investment_amount_krw": 500000,
      "action_intent": "buy_consideration",
      "market_regime_hint": "high_volatility",
      "benchmark_index": "KOSPI"
    },
    "style_axes": {
      "assessment_mode": "quick",
      "axes": [
        {"axis_id": "market_participation", "ratio": -0.2, "confidence": 0.81, "answered_count": 3, "question_count": 3},
        {"axis_id": "loss_tolerance", "ratio": -0.3, "confidence": 0.92, "answered_count": 3, "question_count": 3},
        {"axis_id": "turnover", "ratio": -0.25, "confidence": 0.95, "answered_count": 3, "question_count": 3},
        {"axis_id": "concentration", "ratio": -0.4, "confidence": 0.81, "answered_count": 3, "question_count": 3},
        {"axis_id": "rule_adherence", "ratio": 0.2, "confidence": 0.81, "answered_count": 3, "question_count": 3},
        {"axis_id": "information_reliance", "ratio": 0.16, "confidence": 0.85, "answered_count": 3, "question_count": 3},
        {"axis_id": "urgency", "ratio": 0.44, "confidence": 0.78, "answered_count": 3, "question_count": 3},
        {"axis_id": "drawdown_reaction", "ratio": 0.3, "confidence": 0.7, "answered_count": 3, "question_count": 3}
      ]
    },
    "meta": {
      "schema_version": "1.1.0",
      "source": "profiling_block",
      "confidence": 0.81
    }
  }$profile$::jsonb
)
on conflict (user_id) do update set
  session_id = excluded.session_id,
  surveyed_at = excluded.surveyed_at,
  profile_type = excluded.profile_type,
  max_risk_tier = excluded.max_risk_tier,
  risk_score = excluded.risk_score,
  fomo_score = excluded.fomo_score,
  horizon_score = excluded.horizon_score,
  risk_tolerance = excluded.risk_tolerance,
  time_horizon_months = excluded.time_horizon_months,
  liquidity_need_ratio = excluded.liquidity_need_ratio,
  target_return_annual = excluded.target_return_annual,
  investment_experience_years = excluded.investment_experience_years,
  fomo_index = excluded.fomo_index,
  panic_sell_tendency = excluded.panic_sell_tendency,
  herding_score = excluded.herding_score,
  self_confidence = excluded.self_confidence,
  current_market_anxiety = excluded.current_market_anxiety,
  overheating_caution = excluded.overheating_caution,
  preferred_sectors = excluded.preferred_sectors,
  free_text_raw = excluded.free_text_raw,
  extracted_signals = excluded.extracted_signals,
  conflict_with_survey = excluded.conflict_with_survey,
  confidence_per_field = excluded.confidence_per_field,
  investment_amount_krw = excluded.investment_amount_krw,
  action_intent = excluded.action_intent,
  market_regime_hint = excluded.market_regime_hint,
  benchmark_index = excluded.benchmark_index,
  schema_version = excluded.schema_version,
  confidence = excluded.confidence,
  profile_payload = excluded.profile_payload,
  updated_at = now();

insert into public.avoided_assets (user_id, asset_type)
values
  ('u_minji_001', 'spac'),
  ('u_minji_001', 'managed_stock')
on conflict (user_id, asset_type) do update set
  is_active = true,
  updated_at = now();

insert into public.portfolio_holdings (
  user_id,
  stock_code,
  quantity,
  avg_buy_price,
  display_order
)
values
  ('u_minji_001', '005930', 15, 71200, 1),
  ('u_minji_001', '035720', 8, 48500, 2),
  ('u_minji_001', '068270', 3, 182000, 3),
  ('u_minji_001', '005380', 5, 235000, 4)
on conflict (user_id, stock_code) do update set
  quantity = excluded.quantity,
  avg_buy_price = excluded.avg_buy_price,
  display_order = excluded.display_order,
  is_active = true,
  updated_at = now();

insert into public.watchlist (user_id, stock_code, display_order)
values
  ('u_minji_001', '000660', 1),
  ('u_minji_001', '035420', 2),
  ('u_minji_001', '051910', 3)
on conflict (user_id, stock_code) do update set
  display_order = excluded.display_order,
  is_active = true,
  updated_at = now();

insert into public.predictions (
  stock_code,
  prediction_date,
  data_asof,
  model_type,
  horizon,
  prob_up,
  rank_percentile,
  signal_light,
  return_low,
  return_high,
  return_ci_level,
  calibration_bucket,
  bucket_hit_rate,
  similar_case_count,
  uncertainty,
  horizon_h5,
  horizon_h10,
  horizon_h20,
  horizon_agreement,
  factor_exposures,
  benchmark_index,
  expected_holding_days,
  model_version,
  prediction_hash,
  disclaimer,
  is_recommended,
  is_holding_alert,
  caution,
  display_order
)
values
  (
    '005930',
    '2025-12-30',
    '2025-12-30',
    'stable',
    'h20',
    0.67,
    0.82,
    'positive',
    -0.8,
    4.2,
    0.68,
    '0.60-0.69',
    0.61,
    128,
    0.18,
    'up',
    'up',
    'up',
    'aligned',
    '{"momentum": 0.31, "volatility": -0.12}'::jsonb,
    'KOSPI',
    20,
    'stable-lgbm-v1.0',
    'demo-005930-20260707-stable',
    '투자 자문이 아닌 연구용 참고 신호입니다.',
    true,
    false,
    null,
    1
  ),
  (
    '005380',
    '2025-12-30',
    '2025-12-30',
    'stable',
    'h20',
    0.75,
    0.95,
    'strong_positive',
    0.6,
    7.2,
    0.68,
    '0.70-0.79',
    0.66,
    52,
    0.13,
    'up',
    'up',
    'up',
    'aligned',
    '{"momentum": 0.43, "volume": 0.22}'::jsonb,
    'KOSPI',
    20,
    'stable-lgbm-v1.0',
    'demo-005380-20260707-stable',
    '투자 자문이 아닌 연구용 참고 신호입니다.',
    true,
    false,
    null,
    2
  ),
  (
    '068270',
    '2025-12-30',
    '2025-12-30',
    'stable',
    'h20',
    0.55,
    0.59,
    'neutral',
    -2.0,
    7.4,
    0.68,
    '0.50-0.59',
    0.57,
    34,
    0.32,
    'up',
    'up',
    'flat',
    'mixed',
    '{"momentum": 0.08, "volatility": 0.38}'::jsonb,
    'KOSPI',
    20,
    'stable-lgbm-v1.0',
    'demo-068270-20260707-stable',
    '투자 자문이 아닌 연구용 참고 신호입니다.',
    false,
    true,
    '성향 기준 허용 범위(4·5등급)를 벗어난 변동성 특성을 가진 종목입니다.',
    3
  ),
  (
    '035720',
    '2025-12-30',
    '2025-12-30',
    'stable',
    'h20',
    0.38,
    0.28,
    'negative',
    -5.1,
    1.2,
    0.68,
    '0.30-0.39',
    0.46,
    61,
    0.29,
    'down',
    'down',
    'flat',
    'mixed',
    '{"momentum": -0.36, "volatility": 0.20}'::jsonb,
    'KOSPI',
    20,
    'stable-lgbm-v1.0',
    'demo-035720-20260707-stable',
    '투자 자문이 아닌 연구용 참고 신호입니다.',
    false,
    false,
    null,
    4
  )
on conflict (stock_code, prediction_date, model_type) do update set
  data_asof = excluded.data_asof,
  horizon = excluded.horizon,
  prob_up = excluded.prob_up,
  rank_percentile = excluded.rank_percentile,
  signal_light = excluded.signal_light,
  return_low = excluded.return_low,
  return_high = excluded.return_high,
  return_ci_level = excluded.return_ci_level,
  calibration_bucket = excluded.calibration_bucket,
  bucket_hit_rate = excluded.bucket_hit_rate,
  similar_case_count = excluded.similar_case_count,
  uncertainty = excluded.uncertainty,
  horizon_h5 = excluded.horizon_h5,
  horizon_h10 = excluded.horizon_h10,
  horizon_h20 = excluded.horizon_h20,
  horizon_agreement = excluded.horizon_agreement,
  factor_exposures = excluded.factor_exposures,
  benchmark_index = excluded.benchmark_index,
  expected_holding_days = excluded.expected_holding_days,
  model_version = excluded.model_version,
  prediction_hash = excluded.prediction_hash,
  disclaimer = excluded.disclaimer,
  is_recommended = excluded.is_recommended,
  is_holding_alert = excluded.is_holding_alert,
  caution = excluded.caution,
  display_order = excluded.display_order,
  updated_at = now();

insert into public.prediction_features (
  prediction_id,
  feature,
  label_ko,
  contribution,
  display_order
)
select
  prediction.id,
  seed.feature,
  seed.label_ko,
  seed.contribution,
  seed.display_order
from (
  values
    ('005930', '2025-12-30'::date, 'stable', 'volume_ratio_20d', '최근 거래량이 평소보다 증가했습니다.', 0.31, 1),
    ('005930', '2025-12-30'::date, 'stable', 'volatility_20d', '최근 변동성은 신호를 일부 낮췄습니다.', -0.12, 2),
    ('005380', '2025-12-30'::date, 'stable', 'momentum_20d', '최근 20일 가격 흐름이 견조합니다.', 0.43, 1),
    ('005380', '2025-12-30'::date, 'stable', 'volume_ratio_20d', '거래량 흐름이 신호를 뒷받침합니다.', 0.22, 2),
    ('068270', '2025-12-30'::date, 'stable', 'momentum_20d', '가격 흐름의 방향성이 뚜렷하지 않습니다.', 0.08, 1),
    ('068270', '2025-12-30'::date, 'stable', 'volatility_20d', '최근 변동성이 평소보다 높습니다.', 0.38, 2),
    ('035720', '2025-12-30'::date, 'stable', 'momentum_20d', '최근 가격 흐름이 약세입니다.', -0.36, 1),
    ('035720', '2025-12-30'::date, 'stable', 'volatility_20d', '변동성이 신호의 불확실성을 높입니다.', 0.20, 2)
) as seed (
  stock_code,
  prediction_date,
  model_type,
  feature,
  label_ko,
  contribution,
  display_order
)
join public.predictions as prediction
  on prediction.stock_code = seed.stock_code
  and prediction.prediction_date = seed.prediction_date
  and prediction.model_type = seed.model_type
on conflict (prediction_id, feature) do update set
  label_ko = excluded.label_ko,
  contribution = excluded.contribution,
  display_order = excluded.display_order;

-- 시장 상태: 실데이터 스냅샷과 같은 값(frontend/scripts/build_demo_snapshot.py, KRX 지수·FDR 캐시, 기준일 2025-12-30).
-- 앱은 이 테이블 대신 스냅샷을 직접 읽는다(frontend/lib/queries.ts loadMarketStatus).
insert into public.market_status (
  status_date,
  condition,
  volatility_score,
  volume_score,
  index_quotes
)
values (
  '2025-12-30',
  'caution',
  65,
  77,
  '[
    {"symbol":"KOSPI","label":"KOSPI","value":4214.17,"change":-6.39,"change_percent":-0.15},
    {"symbol":"KOSDAQ","label":"KOSDAQ","value":925.47,"change":-7.12,"change_percent":-0.76},
    {"symbol":"KOSPI200","label":"KOSPI 200","value":605.98,"change":0.29,"change_percent":0.05}
  ]'::jsonb
)
on conflict (status_date) do update set
  condition = excluded.condition,
  volatility_score = excluded.volatility_score,
  volume_score = excluded.volume_score,
  index_quotes = excluded.index_quotes,
  updated_at = now();
