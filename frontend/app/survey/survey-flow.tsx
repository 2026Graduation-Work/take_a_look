"use client";

// 온보딩: (처음이면) 환영 → 성향 진단(한 화면 한 문항) → 결과 확인 → 보유 종목 → 대시보드.
// "다시 진단"으로 들어오면 환영·보유 종목 단계 없이 진단 → 결과 → 대시보드.

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import {
  applyAdjustments,
  AVOIDED_ASSET_DESCRIPTIONS,
  AVOIDED_ASSET_LABELS,
  EXPERIENCE_CHOICES,
  threeAxisSummary,
  type ExperienceChoice,
  type SurveyAnswers,
} from "@/lib/profiling-rules";
import { BIT_LABEL, BIT_SUMMARY, classifyBit } from "@/lib/profiling/bit";
import {
  answersFromPattern,
  AXES,
  LIKERT_OPTIONS,
  questionsForMode,
  type AxisDefinition,
  type StyleQuestion,
} from "@/lib/profiling/style-scoring";
import { saveProfile } from "@/lib/save-profile";
import type { ProfilingOutput, RiskFlag, StyleAxes, StyleAxisId } from "@/lib/types";
import { useOnboarding } from "../components/onboarding-provider";
import SignOutButton from "../components/sign-out-button";
import HoldingsStep from "./holdings-step";
import StepNav from "../components/step-nav";
import Wordmark from "@/components/brand/Wordmark";
import LogoMark from "@/components/brand/LogoMark";
import { SERVICE_NAME } from "@/lib/brand";
import { STORAGE_KEYS } from "@/lib/storage-keys";

const DRAFT_KEY = STORAGE_KEYS.surveyDraft;
const ANSWERS_KEY = STORAGE_KEYS.surveyAnswers;
const ADVANCE_DELAY_MS = 180; // 고른 답이 눌린 것을 보여 준 뒤 다음 문항으로

type SurveyMode = "short" | "quick";
type Stage = "welcome" | "survey" | "result" | "holdings";

type Page =
  | { kind: "style"; axis: AxisDefinition; question: StyleQuestion; number: number; total: number }
  | { kind: "experience" }
  | { kind: "avoided" }
  | { kind: "freeText" };

function buildPages(mode: SurveyMode): Page[] {
  const likert = AXES.flatMap((axis) =>
    questionsForMode(mode)
      .filter((question) => question.type === "likert" && question.axis === axis.id)
      .map((question) => ({ axis, question })),
  );
  return [
    ...likert.map(({ axis, question }, index) => ({
      kind: "style" as const,
      axis,
      question,
      number: index + 1,
      total: likert.length,
    })),
    { kind: "experience" },
    { kind: "avoided" },
    { kind: "freeText" },
  ];
}

const PAGES: Record<SurveyMode, Page[]> = { short: buildPages("short"), quick: buildPages("quick") };

interface Draft {
  mode: SurveyMode;
  page: number;
  style: Record<string, number>;
  experience: ExperienceChoice | "";
  avoided: RiskFlag[];
  freeText: string;
}

const EMPTY_DRAFT: Draft = { mode: "short", page: 0, style: {}, experience: "", avoided: [], freeText: "" };

// 데모 응답: 김민지와 비슷한 추종형 패턴(축 방향 강도 -2~+2)
const DEMO_PATTERN = {
  market_participation: 0,
  loss_tolerance: -1,
  turnover: -1,
  concentration: 0,
  rule_adherence: 0,
  information_reliance: 0,
  urgency: 1,
  drawdown_reaction: 1,
};

function demoDraft(mode: SurveyMode): Draft {
  return {
    mode,
    page: PAGES[mode].length - 1,
    style: answersFromPattern(DEMO_PATTERN, mode) as Record<string, number>,
    experience: "6m_2y",
    avoided: ["spac", "managed_stock"],
    freeText: "남들 다 버는데 나만 뒤처지는 것 같아서 조급해요. 그래도 마이너스 나면 잠을 못 자요.",
  };
}

const DEMO_PORTFOLIO: ProfilingOutput["portfolio"] = {
  holdings: [
    { ticker: "005930", name: "삼성전자", quantity: 15, avg_buy_price: 71200 },
    { ticker: "035720", name: "카카오", quantity: 8, avg_buy_price: 48500 },
    { ticker: "068270", name: "셀트리온", quantity: 3, avg_buy_price: 182000 },
    { ticker: "005380", name: "현대차", quantity: 5, avg_buy_price: 235000 },
  ],
  watchlist: ["000660", "035420", "051910"],
};

// https·localhost는 secure context라 randomUUID가 항상 있다.
const createSessionId = () => `s_${crypto.randomUUID().replaceAll("-", "").slice(0, 12)}`;

function readDraft(key: string = DRAFT_KEY): Draft | null {
  try {
    const parsed: unknown = JSON.parse(window.localStorage.getItem(key) ?? "null");
    if (!parsed || typeof parsed !== "object") return null;
    const draft = { ...EMPTY_DRAFT, ...(parsed as Partial<Draft>) };
    if (draft.mode !== "short" && draft.mode !== "quick") draft.mode = "short";
    draft.page = Math.min(Math.max(0, Math.trunc(draft.page) || 0), PAGES[draft.mode].length - 1);
    return draft;
  } catch {
    return null;
  }
}

function writeDraft(draft: Draft | null, key: string = DRAFT_KEY) {
  try {
    if (draft) window.localStorage.setItem(key, JSON.stringify(draft));
    else window.localStorage.removeItem(key);
  } catch {
    // 저장이 막힌 브라우저(시크릿 모드 등)에서는 중간 저장만 건너뛴다.
  }
}

export default function SurveyFlow() {
  const router = useRouter();
  const { state: onboardingState } = useOnboarding();
  const demo = onboardingState.mode === "demo";
  // 처음 온 사람(프로필 없음)만 환영·보유 종목 단계를 거친다. 저장 후 상태가 바뀌어도 흐름은 유지한다.
  const [firstRun] = useState(onboardingState.status === "needs_survey");
  const [stage, setStage] = useState<Stage>(firstRun ? "welcome" : "survey");
  const [draft, setDraft] = useState<Draft>(EMPTY_DRAFT);
  const [restored, setRestored] = useState(false);
  const [result, setResult] = useState<ProfilingOutput | null>(null);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  // 중간 저장 불러오기. localStorage는 브라우저에서만 읽을 수 있어 마운트 후에 한 번 읽는다.
  // 다시 진단은 지난 답이 채워진 상태로 1번부터 시작한다(답하던 중간 저장이 있으면 그쪽이 먼저).
  useEffect(() => {
    const stored = readDraft();
    const previous = firstRun ? null : readDraft(ANSWERS_KEY);
    if (!stored && !previous) return;
    /* eslint-disable react-hooks/set-state-in-effect -- 외부 저장소에서 한 번 복원 */
    if (stored) {
      setDraft(stored);
      setRestored(true);
    } else {
      setDraft({ ...previous!, page: 0 });
    }
    setStage("survey");
    /* eslint-enable react-hooks/set-state-in-effect */
  }, [firstRun]);

  function update(next: Partial<Draft>) {
    setDraft((current) => {
      const merged = { ...current, ...next };
      writeDraft(merged);
      return merged;
    });
  }

  const pages = PAGES[draft.mode];
  const page = pages[draft.page];
  const last = draft.page === pages.length - 1;

  function goTo(index: number) {
    update({ page: Math.min(Math.max(0, index), pages.length - 1) });
  }

  // 고르면 바로 다음 문항으로. 이전 버튼으로 되돌릴 수 있다.
  function answerAndAdvance(next: Partial<Draft>) {
    const from = draft.page;
    update(next);
    window.setTimeout(() => {
      setDraft((current) => {
        if (current.page !== from) return current;
        const moved = { ...current, page: Math.min(from + 1, PAGES[current.mode].length - 1) };
        writeDraft(moved);
        return moved;
      });
    }, ADVANCE_DELAY_MS);
  }

  function payload(adjusted?: Partial<Record<StyleAxisId, number>>): SurveyAnswers {
    return {
      user_id: "u_minji_001",
      session_id: result?.session_id ?? createSessionId(),
      timestamp: result?.timestamp ?? new Date().toISOString(),
      style: draft.style,
      mode: draft.mode,
      experience: draft.experience as ExperienceChoice,
      avoided_assets: draft.avoided,
      free_text: draft.freeText,
      ...(adjusted && Object.keys(adjusted).length ? { adjusted_axes: adjusted } : {}),
      preferred_sectors: ["semiconductor", "healthcare"],
      // 보유 종목은 다음 단계(또는 보유 종목 화면)에서 따로 저장한다. 데모 계정만 김민지 보유 종목을 쓴다.
      ...(demo ? { portfolio: DEMO_PORTFOLIO } : {}),
      investment_amount_krw: 500000,
      action_intent: "buy_consideration",
      market_regime_hint: "high_volatility",
      benchmark_index: "KOSPI",
    };
  }

  async function requestProfile(body: SurveyAnswers): Promise<ProfilingOutput> {
    const response = await fetch("/api/profiling", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const parsed = (await response.json()) as ProfilingOutput | { error: string };
    if (!response.ok) {
      throw new Error("error" in parsed ? parsed.error : "결과를 만들지 못했어요. 잠시 뒤 다시 눌러 주세요.");
    }
    return parsed as ProfilingOutput;
  }

  async function run(task: () => Promise<void>) {
    setSubmitting(true);
    setError("");
    try {
      await task();
    } catch (taskError) {
      setError(taskError instanceof Error ? taskError.message : "결과를 만들지 못했어요. 잠시 뒤 다시 눌러 주세요.");
    } finally {
      setSubmitting(false);
    }
  }

  function showResult() {
    void run(async () => {
      setResult(await requestProfile(payload()));
      setStage("result");
    });
  }

  // 결과 화면의 "다음"(다시 진단이면 "저장")을 눌러야 저장한다. 조정했으면 조정값으로 다시 계산해 저장한다.
  function confirm(adjusted: Partial<Record<StyleAxisId, number>>) {
    void run(async () => {
      const profile = Object.keys(adjusted).length ? await requestProfile(payload(adjusted)) : result!;
      await saveProfile(profile, onboardingState.mode);
      writeDraft({ ...draft, page: 0 }, ANSWERS_KEY);
      writeDraft(null);
      setResult(profile);
      if (firstRun) setStage("holdings");
      else router.push("/");
    });
  }

  // 16문항 → 24문항: 이미 답한 문항은 그대로 두고 남은 문항부터 이어서 답한다.
  function moreAccurate() {
    const quickPages = PAGES.quick;
    const firstOpen = quickPages.findIndex(
      (candidate) => candidate.kind === "style" && draft.style[candidate.question.id] === undefined,
    );
    update({ mode: "quick", page: Math.max(0, firstOpen) });
    setResult(null);
    setStage("survey");
  }

  function restart() {
    writeDraft(null);
    writeDraft(null, ANSWERS_KEY);
    setDraft(EMPTY_DRAFT);
    setResult(null);
    setRestored(false);
    setError("");
    setStage("survey");
  }

  const step = stage === "holdings" ? 2 : 1;

  return (
    <div className="min-h-dvh bg-page">
      <header className="sticky top-0 z-50 glass-bar">
        <div className="mx-auto flex min-h-14 w-full max-w-[880px] items-center gap-3 px-4 sm:px-8">
          <Link href="/" className="flex min-h-11 flex-none items-center whitespace-nowrap text-lg hover:no-underline">
            <Wordmark size={26} compact />
          </Link>
          {firstRun ? (
            <ol aria-label="시작 단계" className="m-0 flex list-none items-center gap-2 p-0 text-xs sm:gap-3">
              {["성향", "보유 종목", "시작"].map((label, index) => (
                <li
                  key={label}
                  aria-current={index + 1 === step ? "step" : undefined}
                  className={`whitespace-nowrap ${index + 1 === step ? "font-medium text-ink" : "text-muted"}`}
                >
                  {index + 1} {label}
                </li>
              ))}
            </ol>
          ) : (
            <span className="text-sm font-medium text-body">투자 성향 진단</span>
          )}
          <div className="ml-auto flex items-center gap-3">
            {stage === "survey" && demo && (
              <button type="button" onClick={() => update(demoDraft(draft.mode))} className="btn-text whitespace-nowrap text-xs">
                <span className="sm:hidden">데모 응답</span>
                <span className="hidden sm:inline">데모 응답 불러오기</span>
              </button>
            )}
            <SignOutButton />
          </div>
        </div>
      </header>

      <main className="mx-auto flex w-full max-w-[720px] flex-col px-4 py-8 sm:px-8 sm:py-12">
        {stage === "welcome" && <Welcome onStart={() => setStage("survey")} />}
        {stage === "survey" && (
          <QuestionPage
            draft={draft}
            page={page}
            last={last}
            restored={restored}
            submitting={submitting}
            error={error}
            onAnswer={answerAndAdvance}
            onUpdate={update}
            onBack={() => goTo(draft.page - 1)}
            onNext={() => (last ? showResult() : goTo(draft.page + 1))}
            onRestart={restart}
          />
        )}
        {stage === "result" && result && (
          <ResultView
            result={result}
            submitting={submitting}
            error={error}
            nextLabel={firstRun ? "다음" : "저장"}
            canBeMoreAccurate={draft.mode === "short"}
            onConfirm={confirm}
            onMoreAccurate={moreAccurate}
            onBack={() => setStage("survey")}
          />
        )}
        {stage === "holdings" && (
          <HoldingsStep
            mode={onboardingState.mode}
            onBack={() => setStage("result")}
            onDone={() => router.push("/")}
          />
        )}
      </main>
    </div>
  );
}

function Welcome({ onStart }: { onStart: () => void }) {
  const steps = [
    ["내 성향 알기", "16개 질문으로 투자 습관을 알아봐요. 2분이면 끝나요."],
    ["내 종목 등록", "가진 주식을 넣으면 그 종목의 오늘 신호를 먼저 보여 드려요."],
    ["오늘 확인할 것만 보기", "대시보드 맨 위 한 줄로 오늘 볼 것을 알려 드려요."],
  ] as const;
  return (
    <section aria-labelledby="welcome-title" className="surface flex flex-col gap-8 px-6 py-10 sm:px-10">
      <div className="flex flex-col gap-2">
        <LogoMark size={48} className="mb-2" />
        <h1 id="welcome-title" className="text-3xl font-semibold">
          {SERVICE_NAME}은 이렇게 도와줘요
        </h1>
      </div>
      <ol className="m-0 flex list-none flex-col gap-5 p-0">
        {steps.map(([title, body], index) => (
          <li key={title} className="flex gap-4">
            <span className="grid size-8 flex-none place-items-center rounded-full bg-track text-sm font-semibold tabular-nums">
              {index + 1}
            </span>
            <span className="flex flex-col gap-1">
              <span className="text-base font-medium">{title}</span>
              <span className="text-sm text-body">{body}</span>
            </span>
          </li>
        ))}
      </ol>
      <p className="-mt-2 m-0 text-sm text-body">맞고 틀린 답은 없어요. 요즘의 나와 가까운 쪽을 고르면 돼요.</p>
      <StepNav nextLabel="시작하기" onNext={onStart} />
    </section>
  );
}

function QuestionPage({
  draft,
  page,
  last,
  restored,
  submitting,
  error,
  onAnswer,
  onUpdate,
  onBack,
  onNext,
  onRestart,
}: {
  draft: Draft;
  page: Page;
  last: boolean;
  restored: boolean;
  submitting: boolean;
  error: string;
  onAnswer: (next: Partial<Draft>) => void;
  onUpdate: (next: Partial<Draft>) => void;
  onBack: () => void;
  onNext: () => void;
  onRestart: () => void;
}) {
  const total = PAGES[draft.mode].length;
  // 고르면 자동으로 넘어가므로 "다음"은 이전으로 돌아왔다가 다시 앞으로 갈 때 쓴다. 답한 문항에서만 켜진다.
  const answered =
    page.kind === "style"
      ? draft.style[page.question.id] !== undefined
      : page.kind === "experience"
        ? draft.experience !== ""
        : true; // 제외 항목·걱정되는 점은 비워 둬도 된다
  const progress = ((draft.page + 1) / total) * 100;
  const label =
    page.kind === "style"
      ? `질문 ${page.number}/${page.total}`
      : `마무리 ${["experience", "avoided", "freeText"].indexOf(page.kind) + 1}/3`;

  return (
    <section className="surface flex min-h-[520px] flex-col px-6 py-8 sm:px-10">
      <div className="flex flex-col gap-2">
        <div className="flex items-baseline gap-3">
          <span className="text-xs font-medium text-ink tabular-nums">{label}</span>
          {page.kind === "style" && <span className="text-xs text-muted">{page.axis.section}</span>}
          <button type="button" onClick={onRestart} className="btn-text ml-auto text-xs">
            처음부터 새로 하기
          </button>
        </div>
        <div
          className="h-1 overflow-hidden rounded-full bg-track"
          role="progressbar"
          aria-label="진단 진행률"
          aria-valuemin={1}
          aria-valuemax={total}
          aria-valuenow={draft.page + 1}
        >
          <div className="h-full rounded-full bg-brand-accent transition-[width]" style={{ width: `${progress}%` }} />
        </div>
      </div>

      {restored && draft.page > 0 && (
        <p className="mb-0 mt-5 rounded-md bg-field px-4 py-3 text-sm text-body">저장해 둔 응답을 불러왔어요. 이어서 답하면 돼요.</p>
      )}

      <div className="mt-8 flex flex-1 flex-col">
        {page.kind === "style" && (
          <fieldset key={page.question.id} className="m-0 flex flex-col gap-5 border-0 p-0">
            <p className="m-0 text-sm text-muted">{page.axis.help}</p>
            <legend className="sr-only">{page.question.text}</legend>
            <h1 aria-hidden className="text-2xl font-semibold leading-snug">
              {page.question.text}
            </h1>
            <div className="flex flex-col gap-2">
              {LIKERT_OPTIONS.map((option) => (
                <ChoiceRow
                  key={option.value}
                  type="radio"
                  name={page.question.id}
                  label={option.label}
                  selected={draft.style[page.question.id] === option.value}
                  onChange={() => onAnswer({ style: { ...draft.style, [page.question.id]: option.value } })}
                />
              ))}
            </div>
          </fieldset>
        )}

        {page.kind === "experience" && (
          <fieldset className="m-0 flex flex-col gap-5 border-0 p-0">
            <legend className="sr-only">직접 투자한 경험은 얼마나 되나요?</legend>
            <h1 aria-hidden className="text-2xl font-semibold leading-snug">
              직접 투자한 경험은 얼마나 되나요?
            </h1>
            <p className="m-0 text-sm text-muted">주식이나 ETF를 직접 사고판 기간으로 골라 주세요.</p>
            <div className="flex flex-col gap-2">
              {EXPERIENCE_CHOICES.map((choice) => (
                <ChoiceRow
                  key={choice.id}
                  type="radio"
                  name="experience"
                  label={choice.label}
                  selected={draft.experience === choice.id}
                  onChange={() => onAnswer({ experience: choice.id })}
                />
              ))}
            </div>
          </fieldset>
        )}

        {page.kind === "avoided" && (
          <fieldset className="m-0 flex flex-col gap-5 border-0 p-0">
            <legend className="sr-only">목록에서 빼고 싶은 종목 유형이 있나요?</legend>
            <h1 aria-hidden className="text-2xl font-semibold leading-snug">
              목록에서 빼고 싶은 종목 유형이 있나요?
            </h1>
            <p className="m-0 text-sm text-muted">
              직접 고른 항목만 목록에서 빠져요. 성향 점수로는 종목을 빼지 않아요. 없으면 넘어가도 돼요.
            </p>
            <div className="flex flex-col gap-2">
              {(Object.entries(AVOIDED_ASSET_LABELS) as [RiskFlag, string][]).map(([flag, flagLabel]) => (
                <ChoiceRow
                  key={flag}
                  type="checkbox"
                  name="avoided"
                  label={flagLabel}
                  detail={AVOIDED_ASSET_DESCRIPTIONS[flag]}
                  selected={draft.avoided.includes(flag)}
                  onChange={() =>
                    onUpdate({
                      avoided: draft.avoided.includes(flag)
                        ? draft.avoided.filter((item) => item !== flag)
                        : [...draft.avoided, flag],
                    })
                  }
                />
              ))}
            </div>
          </fieldset>
        )}

        {page.kind === "freeText" && (
          <div className="flex flex-col gap-5">
            <h1 className="text-2xl font-semibold leading-snug">요즘 투자하면서 걱정되는 점이 있나요?</h1>
            <p className="m-0 text-sm text-muted">점수 계산에는 쓰지 않고 결과를 설명할 때 참고만 해요. 비워 둬도 돼요.</p>
            <textarea
              value={draft.freeText}
              onChange={(event) => onUpdate({ freeText: event.target.value })}
              rows={5}
              maxLength={500}
              aria-label="요즘 걱정되는 점"
              placeholder="예: 남들보다 뒤처질까 조급하지만 손실도 많이 걱정돼요."
              className="w-full resize-none rounded-md bg-field px-4 py-3 text-sm text-ink outline-none focus:bg-white focus:ring-2 focus:ring-brand/30"
            />
          </div>
        )}

        {error && (
          <p role="alert" className="mt-4 text-sm text-danger">
            {error}
          </p>
        )}

        <StepNav
          className="mt-auto pt-8"
          onBack={onBack}
          backDisabled={draft.page === 0 || submitting}
          nextLabel={submitting ? "계산 중" : last ? "완료" : "다음"}
          onNext={onNext}
          nextDisabled={!answered || submitting}
        />
      </div>
    </section>
  );
}

function ChoiceRow({
  type,
  name,
  label,
  detail,
  selected,
  onChange,
}: {
  type: "radio" | "checkbox";
  name: string;
  label: string;
  detail?: string;
  selected: boolean;
  onChange: () => void;
}) {
  return (
    <label
      className={`flex min-h-14 cursor-pointer items-center gap-3 rounded-md px-4 py-3 text-base transition-colors ${
        selected ? "bg-brand-soft font-medium text-brand" : "bg-field text-body hover:bg-track"
      }`}
    >
      <input
        type={type}
        name={name}
        checked={selected}
        onChange={onChange}
        // 되돌아와서 이미 고른 답을 다시 눌러도 다음으로 넘어가게 한다(radio는 이때 change가 없다)
        onClick={type === "radio" && selected ? onChange : undefined}
        className="size-4 flex-none accent-[var(--color-brand)]"
      />
      <span className="flex flex-col gap-1">
        <span>{label}</span>
        {detail && <span className="text-xs font-normal text-muted">{detail}</span>}
      </span>
    </label>
  );
}

function AxisGauge({
  label,
  value,
  caption,
  left,
  right,
}: {
  label: string;
  value: number;
  caption: string;
  left: string;
  right: string;
}) {
  return (
    <div className="flex min-w-0 flex-col gap-2">
      <div className="flex items-baseline gap-2">
        <span className="text-sm font-medium text-ink">{label}</span>
        <span className="ml-auto text-xl font-semibold tabular-nums text-ink">{value}</span>
      </div>
      <div className="h-2 overflow-hidden rounded bg-track">
        <div className="h-full rounded bg-brand-accent" style={{ width: `${value}%` }} />
      </div>
      <span className="flex justify-between text-2xs text-muted">
        <span>0 {left}</span>
        <span>100 {right}</span>
      </span>
      <span className="text-xs text-muted">{caption}</span>
    </div>
  );
}

const HORIZON_LABEL = { short: "단기", mid: "중기", long: "장기" } as const;

// 설문 결과. readOnly는 저장된 결과를 다시 보는 화면(/profile): 조정·24문항 없이 뒤로 / 다시 진단만.
export function ResultView({
  result,
  submitting = false,
  error = "",
  nextLabel,
  canBeMoreAccurate = false,
  onConfirm,
  onMoreAccurate,
  onBack,
  readOnly = false,
}: {
  result: ProfilingOutput;
  submitting?: boolean;
  error?: string;
  nextLabel: string;
  canBeMoreAccurate?: boolean;
  onConfirm: (adjusted: Partial<Record<StyleAxisId, number>>) => void;
  onMoreAccurate?: () => void;
  onBack: () => void;
  readOnly?: boolean;
}) {
  const [adjusting, setAdjusting] = useState(false);
  const [adjusted, setAdjusted] = useState<Partial<Record<StyleAxisId, number>>>({});
  const scored = result.style_axes!;
  const styleAxes: StyleAxes = applyAdjustments(scored, adjusted);
  const bit = classifyBit(styleAxes);
  const summary = threeAxisSummary(styleAxes);
  const changed = Object.keys(adjusted).length > 0;
  const avoidedLabels = result.constraints.avoided_assets.map((asset) => AVOIDED_ASSET_LABELS[asset]);

  return (
    <section className="surface overflow-hidden">
      <div className="border-b border-line-soft px-6 py-7 sm:px-10">
        <span className="text-xs font-semibold text-brand">{readOnly ? "내 투자 성향" : "진단 결과"}</span>
        <h1 data-bit-type={bit.lowConfidence ? "low_confidence" : bit.type} className="mt-2 text-3xl font-semibold text-ink sm:text-3xl">
          {bit.lowConfidence ? "유형 확인 중" : BIT_LABEL[bit.type]}
        </h1>
        <p className="mt-1 text-sm font-semibold text-muted">
          {bit.lowConfidence
            ? "몇몇 질문의 답이 서로 엇갈려 유형을 단정하지 않았어요. 다시 답하거나 아래에서 직접 조정할 수 있어요."
            : BIT_SUMMARY[bit.type]}
        </p>
        <p className="mt-3 text-xs leading-5 text-muted">
          행동투자자 유형에서 착안한 분류예요. 금융회사의 투자자 등급과는 다른 것이고, 정보를 보여 주는
          순서와 체크포인트에만 쓰며 종목을 거르지 않아요.
        </p>
        {canBeMoreAccurate && (
          <button type="button" onClick={onMoreAccurate} className="btn-text mt-2 text-xs">
            더 정확하게 진단하기(24문항)
          </button>
        )}
      </div>

      <div className="px-6 py-8 sm:px-10 sm:py-10">
        <div className="grid gap-8 md:grid-cols-3">
          <AxisGauge
            label="위험 감수"
            value={summary.riskTaking}
            caption="손실을 견디는 정도와 소수 종목 집중 선호를 합친 값"
            left="원금 보전"
            right="수익 기회"
          />
          <AxisGauge
            label="흔들림 민감도"
            value={summary.sensitivity}
            caption="조급함·하락 시 이탈·주변 의견 추종을 합친 값"
            left="차분함"
            right="흔들림 큼"
          />
          <AxisGauge
            label="투자 기간"
            value={summary.horizonScore}
            caption={`${HORIZON_LABEL[summary.horizon]} 보유 성향 · 보유 기간과 회전 문항 기준`}
            left="장기 보유"
            right="단기 매매"
          />
        </div>

        {(result.contradictions?.length ?? 0) > 0 && (
          <div className="mt-8 flex flex-col gap-2 rounded-lg bg-field px-4 py-3">
            <span className="text-sm font-medium text-body">답변 중 서로 부딪히는 부분이 있어요</span>
            {result.contradictions!.map((item) => (
              <p key={item.id} className="m-0 text-sm leading-6 text-body">
                {item.observation} <span className="text-body">→ {item.follow_up_question}</span>
              </p>
            ))}
          </div>
        )}

        <div className="mt-8 border-t border-line-soft pt-6">
          <div className="flex flex-wrap items-center gap-2">
            <span className="mr-2 text-sm font-medium text-ink">제외할 종목 유형</span>
            {avoidedLabels.length ? (
              avoidedLabels.map((label) => (
                <span key={label} className="rounded-sm bg-track px-3 py-1 text-xs text-body">
                  {label}
                </span>
              ))
            ) : (
              <span className="text-sm text-muted">선택한 항목 없음</span>
            )}
          </div>
        </div>

        {adjusting && (
          <div id="style-axes-adjust" className="mt-8 flex flex-col gap-3 rounded-md bg-field px-5 py-5">
            <p className="m-0 text-sm text-body">
              결과가 나와 다르다고 느껴지는 축만 옮겨 주세요. 유형과 위의 요약이 바로 다시 계산돼요.
            </p>
            <div className="grid grid-cols-1 gap-x-8 gap-y-3 md:grid-cols-2">
              {AXES.map((axis) => {
                const ratio = styleAxes.axes.find(({ axis_id }) => axis_id === axis.id)!.ratio;
                return (
                  <label key={axis.id} className="flex flex-col gap-1 text-xs">
                    <span className="flex items-center gap-2">
                      <strong className="text-ink">{axis.section}</strong>
                      <span className="ml-auto font-medium tabular-nums text-ink">
                        {ratio > 0 ? "+" : ""}
                        {ratio.toFixed(2)}
                      </span>
                    </span>
                    <input
                      type="range"
                      min={-1}
                      max={1}
                      step={0.05}
                      value={ratio}
                      aria-label={axis.section}
                      onChange={(event) =>
                        setAdjusted((current) => ({ ...current, [axis.id]: Number(event.target.value) }))
                      }
                      className="accent-brand"
                    />
                    <span className="flex justify-between text-2xs text-muted">
                      <span>{axis.negative_label}</span>
                      <span>{axis.positive_label}</span>
                    </span>
                  </label>
                );
              })}
            </div>
          </div>
        )}

        {error && (
          <p role="alert" className="mt-4 text-sm font-semibold text-danger">
            {error}
          </p>
        )}

        <div className="mt-8 flex flex-col gap-4 border-t border-line-soft pt-6">
          {!readOnly && (
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
            {adjusting ? (
              <button
                type="button"
                onClick={() => {
                  setAdjusted({});
                  setAdjusting(false);
                }}
                disabled={submitting}
                className="btn-text text-sm"
              >
                조정 취소
              </button>
            ) : (
              <button type="button" onClick={() => setAdjusting(true)} aria-controls="style-axes-adjust" className="btn-text text-sm">
                결과가 나와 다르면 직접 조정하기
              </button>
            )}
          </div>
          )}
          <StepNav
            onBack={onBack}
            backLabel={readOnly ? "뒤로" : "이전"}
            backDisabled={submitting}
            nextLabel={submitting ? "저장 중" : nextLabel}
            onNext={() => onConfirm(changed ? adjusted : {})}
            nextDisabled={submitting}
          />
        </div>
      </div>
    </section>
  );
}
