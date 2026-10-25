import type { Metadata } from "next";
import Link from "next/link";
import BrandHeader from "../components/brand-header";
import GuideAccount from "../guide/guide-account";
import DisclaimerFooter from "../components/disclaimer-footer";
import { SERVICE_NAME } from "@/lib/brand";

// 개인정보 처리방침(개인정보 보호법 제30조 공개 의무). 로그인 없이 열린다(onboarding-provider).
// 실제 코드 기준: 테이블은 supabase/migrations(users, ips_profiles, avoided_assets, portfolio_holdings, watchlist, stock_notes),
// 탈퇴는 0008 delete_my_account(auth.users 삭제 → 연결 행 cascade), 캡처는 lib/holdings-ocr(기기 안 워커), 데모는 localStorage.
// 항목이나 위탁처가 바뀌면 이 파일과 시행일을 같이 고친다.
export const metadata: Metadata = {
  title: "개인정보 처리방침",
  description: `${SERVICE_NAME}이 어떤 개인정보를 왜 모으고 언제 지우는지 안내해요.`,
};

const EFFECTIVE = "2026년 10월 26일";
const CONTACT = "fourmi103@g.skku.edu";

const ITEMS: [string, string, string][] = [
  ["계정", "이메일, 비밀번호(암호화해 저장), 화면에 쓰는 이름", "로그인, 화면 인사"],
  ["성향 진단", "설문 답으로 계산한 투자 성향 결과, 제외할 종목 유형, 자유롭게 적은 걱정(선택)", "종목 화면의 확인할 것과 근거 보는 순서를 내 성향에 맞추기"],
  ["보유 종목", "종목, 수량, 평균 매입가(선택)", "대시보드 '내 포트폴리오'와 평단 대비 수익률 표시"],
  ["관심 종목과 판단 메모", "고른 종목, 직접 쓴 메모와 쓴 날짜", "대시보드 관심 종목, 종목 화면의 지난 메모"],
];

export default function PrivacyPage() {
  return (
    <div className="w-full">
      <BrandHeader>
        <GuideAccount />
      </BrandHeader>

      <main className="page pb-12 pt-8">
        <article className="page-narrow flex flex-col gap-12">
          <div className="flex flex-col gap-2 px-1">
            <h1 className="text-3xl font-semibold">개인정보 처리방침</h1>
            <p className="m-0 text-sm text-muted">시행일 {EFFECTIVE}</p>
            <p className="m-0 text-base text-body">
              {SERVICE_NAME}은 성균관대학교 졸업작품으로 만든 무료 서비스예요. 판단 근거를 보여 주는 데 꼭 필요한 정보만 모으고, 팔거나 광고에 쓰지 않아요.
            </p>
          </div>

          <Section id="items" title="모으는 정보와 쓰는 곳">
            <dl className="m-0 flex flex-col gap-4">
              {ITEMS.map(([name, what, why]) => (
                <div key={name} className="flex flex-col gap-1">
                  <dt className="text-base font-medium text-ink">{name}</dt>
                  <dd className="m-0 text-sm text-body">{what}</dd>
                  <dd className="m-0 text-xs text-muted">쓰는 곳: {why}</dd>
                </div>
              ))}
            </dl>
            <p className="m-0 text-sm text-body">
              증권사 계좌와는 연결하지 않아요. 주민등록번호, 계좌번호, 연락처는 모으지 않아요.
            </p>
          </Section>

          <Section id="capture" title="캡처 사진과 데모">
            <p className="m-0 text-sm text-body">
              보유 종목 화면 캡처는 이 기기의 브라우저 안에서만 읽고 어디에도 보내지 않아요. 사진과 읽은 글자는 저장하지 않고, 확인한 종목과 수량만 내가 저장을 누를 때 저장돼요.
            </p>
            <p className="m-0 text-sm text-body">
              데모로 둘러볼 때 넣은 설문 결과, 보유 종목, 관심 종목과 메모는 이 브라우저에만 저장되고 서버로 보내지 않아요. 로그아웃하면 보유 종목과 설문 결과를 지우고, 나머지는 브라우저 저장소를 지우면 사라져요.
            </p>
          </Section>

          <Section id="keep" title="보관 기간과 삭제">
            <p className="m-0 text-sm text-body">
              계정을 삭제할 때까지 보관하고, 삭제하면 위 정보를 바로 모두 지워요. 지운 정보는 되돌릴 수 없어요.
            </p>
            <p className="m-0 text-sm text-body">
              삭제하는 곳: 로그인 뒤 이름 메뉴 › 계정 설정 › <Link href="/profile#account" className="text-brand hover:underline">계정 삭제</Link>. 정보를 보거나 고치는 것은 각 화면(내 투자 성향, 보유 종목, 종목 화면)에서 바로 할 수 있어요.
            </p>
          </Section>

          <Section id="vendors" title="처리를 맡기는 곳">
            <dl className="m-0 flex flex-col gap-4">
              <div className="flex flex-col gap-1">
                <dt className="text-base font-medium text-ink">Supabase</dt>
                <dd className="m-0 text-sm text-body">계정과 위 정보의 저장, 로그인 처리. 서버 위치는 서울이에요.</dd>
              </div>
              <div className="flex flex-col gap-1">
                <dt className="text-base font-medium text-ink">Vercel</dt>
                <dd className="m-0 text-sm text-body">웹사이트 전송. 접속 기록(IP 주소, 접속 시각, 브라우저 정보)이 이 회사의 운영 기록에 남을 수 있어요.</dd>
              </div>
            </dl>
            <p className="m-0 text-sm text-body">로그인 상태를 유지하려고 브라우저 저장소를 써요. 광고나 방문 분석 도구는 쓰지 않아요.</p>
          </Section>

          <Section id="contact" title="문의">
            <p className="m-0 text-sm text-body">
              개인정보 보호 책임자: {SERVICE_NAME} 팀장, <a href={`mailto:${CONTACT}`} className="text-brand hover:underline">{CONTACT}</a>
            </p>
            <p className="m-0 text-sm text-body">열람, 정정, 삭제, 처리 정지를 요청하면 지체 없이 처리하고 결과를 알려 드려요.</p>
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
