import type { Metadata } from "next";
import Link from "next/link";
import BrandHeader from "../components/brand-header";
import GuideAccount from "./guide-account";
import DisclaimerFooter from "../components/disclaimer-footer";
import { DISCLAIMER, SERVICE_NAME } from "@/lib/brand";
import { TERM_INFO } from "@/lib/copy-glossary";

// 이용 안내(로그인 없이 열림, 지도교수 피드백 "처음 사용자에게 취지와 흐름 안내"). 위에서 아래 한 줄기, 맨 위 목차.
// 강제 튜토리얼, 코치마크는 두지 않는다(NN/g 모바일 튜토리얼 연구: 성공률을 높이지 않고 앱을 더 어렵게 느끼게 함).
// 용어 모음은 ⓘ와 같은 출처(TERM_INFO)에서 만든다. 문구를 따로 쓰지 않는다.
export const metadata: Metadata = {
  title: "이용 안내",
  description: `${SERVICE_NAME}이 무엇을 하는 서비스인지, 어떤 순서로 보면 되는지 안내해요.`,
};

const SECTIONS = [
  ["about", "Take a Look은 이런 서비스예요"],
  ["start", "이렇게 시작해요"],
  ["routine", "하루 5분 공부 루틴"],
  ["screens", "화면 읽는 법"],
  ["terms", "용어 모음"],
  ["notes", "알아 둘 점"],
] as const;

const START: [string, string, string][] = [
  ["성향 진단", "16개 질문으로 내 투자 습관을 알아봐요. 결과에 따라 확인할 것과 근거를 보는 순서가 달라져요.", "/survey"],
  ["보유 종목 넣기", "가진 주식과 수량을 넣어요. 증권 앱 캡처로 한 번에 불러올 수도 있어요.", "/portfolio"],
  ["대시보드 확인", "맨 위 한 문장이 오늘 내 종목에서 볼 것을 알려 줘요.", "/"],
];

const ROUTINE = [
  "대시보드 맨 위 요약 문장을 읽어요.",
  "'어제와 달라진 근거'에서 신호가 바뀐 내 종목을 열어요.",
  "종목 상세의 네 탭에서 근거 숫자와 비교 기준을 봐요.",
  "생각한 것을 판단 메모로 남겨요.",
  "1주 뒤 메모를 다시 열어 그때 생각과 지금을 견줘 봐요.",
];

const SCREENS: [string, string][] = [
  ["대시보드", "맨 위 문장이 결론이에요. 왼쪽은 내 포트폴리오와 어제와 달라진 근거, 오른쪽은 신호가 강한 종목이에요. 1주와 4주를 바꾸면 화면 전체가 같은 기간을 따라요."],
  ["종목 상세 네 탭", "시장 분위기, 누가 사고팔았나, 모델이 본 이유, 재무 상태를 각각 질문 하나로 답해요. 탭마다 결론 문장, 비교 기준이 붙은 숫자, 왜 봐야 하는지 한 줄, 계산 근거 순서로 읽으면 돼요. 탭 순서는 내 성향에 맞춰 바뀌어요."],
  ["모델 성적표", "모델이 과거에 상승 종목을 얼마나 위로 세웠는지(AUC)와 모의 투자 결과를 보여 줘요. 화면 맨 아래 면책 문구의 링크에서 열려요."],
];

const NOTES = [
  "모델 신호는 과거 비슷한 경우의 통계예요. 앞으로의 가격을 맞히는 값이 아니고 틀릴 수 있어요.",
  "기준일은 시장 바의 ⓘ를 누르면 맨 아래 줄에 있어요. 데이터가 2영업일 넘게 밀리면 시장 바와 그 카드에 따로 적어요.",
  "코스피에 상장된 주식(보통주, 우선주)을 다뤄요. ETF, ETN, 해외 주식은 아직 다루지 않아요.",
  DISCLAIMER,
];

export default function GuidePage() {
  const terms = Object.values(TERM_INFO).sort((a, b) => a.label.localeCompare(b.label, "ko"));
  return (
    <div className="w-full">
      <BrandHeader>
        <GuideAccount />
      </BrandHeader>

      <main className="page pb-12 pt-8">
        <article className="page-wide flex flex-col gap-12">
          <div className="flex flex-col gap-4 px-1">
            <h1 className="text-3xl font-semibold">이용 안내</h1>
            <nav aria-label="목차">
              <ol className="m-0 flex list-none flex-wrap gap-x-4 p-0 text-sm">
                {SECTIONS.map(([id, title], index) => (
                  <li key={id}>
                    <a href={`#${id}`} className="flex min-h-11 items-center text-brand hover:underline">
                      {index + 1}. {title}
                    </a>
                  </li>
                ))}
              </ol>
            </nav>
          </div>

          <Section id="about" title={SECTIONS[0][1]}>
            <p className="m-0 max-w-2xl text-base text-body">
              {SERVICE_NAME}은 살 종목을 골라 주지 않아요. 내가 보는 종목의 판단 근거를 한곳에 모아 쉬운 말로 정리해요. 판단은
              내가 해요.
            </p>
          </Section>

          <Section id="start" title={SECTIONS[1][1]}>
            <ol className="m-0 flex list-none flex-col gap-4 p-0">
              {START.map(([title, body, href], index) => (
                <li key={title} className="flex gap-4">
                  <span className="grid size-8 flex-none place-items-center rounded-full bg-track text-sm font-semibold tabular-nums">{index + 1}</span>
                  <span className="flex flex-col gap-1">
                    <Link href={href} className="-my-2 flex min-h-11 items-center text-base font-medium text-ink">{title}</Link>
                    <span className="text-sm text-body">{body}</span>
                  </span>
                </li>
              ))}
            </ol>
          </Section>

          <Section id="routine" title={SECTIONS[2][1]}>
            <p className="m-0 text-sm text-muted">하루에 하나씩, 근거를 보는 습관을 들이는 예시예요.</p>
            <ol className="m-0 flex list-none flex-col gap-2 p-0">
              {ROUTINE.map((step, index) => (
                <li key={step} className="flex gap-3 text-base text-body">
                  <span className="flex-none text-muted tabular-nums">{index + 1}</span>
                  {step}
                </li>
              ))}
            </ol>
          </Section>

          <Section id="screens" title={SECTIONS[3][1]}>
            <dl className="m-0 flex flex-col gap-5">
              {SCREENS.map(([name, body]) => (
                <div key={name} className="flex flex-col gap-1">
                  <dt className="text-base font-semibold text-ink">{name}</dt>
                  <dd className="m-0 max-w-2xl text-sm text-body">{body}</dd>
                </div>
              ))}
            </dl>
          </Section>

          <Section id="terms" title={SECTIONS[4][1]}>
            <p className="m-0 text-sm text-muted">화면의 ⓘ와 같은 설명이에요.</p>
            <dl className="m-0 flex flex-col gap-4">
              {terms.map((term) => (
                <div key={term.label} className="flex flex-col gap-1">
                  <dt className="text-base font-medium text-ink">{term.label}</dt>
                  <dd className="m-0 max-w-2xl text-sm text-body">{term.define} {term.read}</dd>
                </div>
              ))}
            </dl>
          </Section>

          <Section id="notes" title={SECTIONS[5][1]}>
            <ul className="m-0 flex list-disc flex-col gap-2 pl-5 text-sm text-body">
              {NOTES.map((note) => <li key={note} className="max-w-2xl">{note}</li>)}
            </ul>
          </Section>
        </article>
      </main>
      <DisclaimerFooter fixed={false} />
    </div>
  );
}

function Section({ id, title, children }: { id: string; title: string; children: React.ReactNode }) {
  return (
    <section id={id} aria-labelledby={`${id}-title`} className="flex scroll-mt-20 flex-col gap-4 px-1">
      <h2 id={`${id}-title`} className="text-xl font-semibold">{title}</h2>
      {children}
    </section>
  );
}
