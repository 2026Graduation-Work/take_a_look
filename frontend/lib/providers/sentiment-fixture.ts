// FIXTURE — 실데이터 아님.
// 단, 삼성전자(005930) 감성 점수와 기사 제목은 실제 기사에서 집계했다. 자동 생성 파일이므로 직접 고치지 않는다.
// 생성: python frontend/scripts/build_sentiment_fixture.py --scorer finbert
//       (backend value_pipeline news_agent와 같은 규칙)
// 원천: backend/analysis/text/data/processed/news_corpus.csv, 2025-10-29 ~ 2025-12-31 중 관련 기사가 있는 62일, 채점 1150건
// 감성 백엔드: kr-finbert (snunlp/KR-FinBert-SC), 기사 텍스트 = 제목 + 본문 앞 1000자
// N07 임계: 일별 감성 변화량 |Δ| 61개의 상위 10% 분위수(p90, inclusive 보간) = 0.5044
// 20일 창: 2025-11-28 ~ 2025-12-18. |Δ| >= p90인 가장 늦은 날로 끝나게 실제 날짜 구간을 골랐다.
//   마지막 날 |Δ| = 0.6005 (2025-12-17 +0.8119 → 2025-12-18 +0.2114)
// 데모 기준일(2025-12-30)은 코퍼스 기간 안이라 주가 기간(최근 60거래일)과 겹친다.

import type { SentimentSeries } from "./index";

export const SENTIMENT_SHIFT_P90 = 0.5044;

export const SAMSUNG_SENTIMENT: SentimentSeries = {
  "days": [
    {
      "date": "2025-11-28",
      "score": 0.0294,
      "articleCount": 16
    },
    {
      "date": "2025-11-30",
      "score": -0.1197,
      "articleCount": 6
    },
    {
      "date": "2025-12-01",
      "score": 0.4749,
      "articleCount": 15
    },
    {
      "date": "2025-12-02",
      "score": 0.1164,
      "articleCount": 20
    },
    {
      "date": "2025-12-03",
      "score": 0.5355,
      "articleCount": 29
    },
    {
      "date": "2025-12-04",
      "score": 0.1975,
      "articleCount": 14
    },
    {
      "date": "2025-12-05",
      "score": 0.273,
      "articleCount": 9
    },
    {
      "date": "2025-12-06",
      "score": -0.0264,
      "articleCount": 6
    },
    {
      "date": "2025-12-07",
      "score": 0.5477,
      "articleCount": 7
    },
    {
      "date": "2025-12-08",
      "score": 0.3948,
      "articleCount": 13
    },
    {
      "date": "2025-12-09",
      "score": 0.3545,
      "articleCount": 19
    },
    {
      "date": "2025-12-10",
      "score": 0.2644,
      "articleCount": 18
    },
    {
      "date": "2025-12-11",
      "score": 0.2383,
      "articleCount": 20
    },
    {
      "date": "2025-12-12",
      "score": 0.192,
      "articleCount": 14
    },
    {
      "date": "2025-12-13",
      "score": 0.0,
      "articleCount": 2
    },
    {
      "date": "2025-12-14",
      "score": 0.3432,
      "articleCount": 8
    },
    {
      "date": "2025-12-15",
      "score": 0.1964,
      "articleCount": 23
    },
    {
      "date": "2025-12-16",
      "score": 0.1867,
      "articleCount": 15
    },
    {
      "date": "2025-12-17",
      "score": 0.8119,
      "articleCount": 17
    },
    {
      "date": "2025-12-18",
      "score": 0.2114,
      "articleCount": 26
    }
  ],
  "headlines": [
    {
      "date": "2025-12-18",
      "title": "삼성, 데이터센터용 '소캠2' 엔비디아 손잡고 시장 선점",
      "press": "매일경제"
    },
    {
      "date": "2025-12-18",
      "title": "삼성, 엔비디아에 '소캠2' 샘플 공급 차세대 AI 메모리 시장 선점",
      "press": "머니투데이"
    },
    {
      "date": "2025-12-18",
      "title": "삼성전자, 주름제거 기능 탑재 '비스포크 AI 에어드레서' 출시",
      "press": "머니투데이"
    }
  ]
};
