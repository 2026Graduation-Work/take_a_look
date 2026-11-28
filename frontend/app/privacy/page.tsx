import type { Metadata } from "next";
import Link from "next/link";
import BrandHeader from "../components/brand-header";
import GuideAccount from "../guide/guide-account";
import DisclaimerFooter from "../components/disclaimer-footer";
import { SERVICE_NAME } from "@/lib/brand";
import { PRIVACY_EFFECTIVE, PRIVACY_ITEMS as ITEMS } from "@/lib/privacy";

export const metadata: Metadata = {
  title: "개인정보 처리방침",
  description: `${SERVICE_NAME}이 어떤 개인정보를 왜 모으고 언제 지우는지 안내해요.`,
};

const EFFECTIVE = PRIVACY_EFFECTIVE.replace(/^(\d+)-(\d+)-(\d+)$/, (_, y, m, d) => `${y}년 ${Number(m)}월 ${Number(d)}일`);
const CONTACT = "fourmi103@g.skku.edu";

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
            <p className="m-0 text-sm text-body">
              위 정보는 서비스 이용 계약을 이행하는 데 필요해 처리하고(개인정보 보호법 제15조 1항 4호), 가입할 때 동의도 받아요. 동의한 날짜와 처리방침 판본은 계정 정보에 함께 저장해요.
            </p>
            <p className="m-0 text-sm text-body">
              만 14세 미만은 가입할 수 없어요. 법정대리인 동의를 받는 절차가 없기 때문이에요.
            </p>
          </Section>

          <Section id="capture" title="캡처 사진과 데모">
            <p className="m-0 text-sm text-body">
              보유 종목 화면 캡처는 이 기기의 브라우저 안에서만 읽고 어디에도 보내지 않아요. 사진과 읽은 글자는 저장하지 않고, 확인한 종목과 수량만 내가 저장을 누를 때 저장돼요.
            </p>
            <p className="m-0 text-sm text-body">
              데모로 둘러볼 때 넣은 설문 결과, 보유 종목, 관심 종목과 메모는 이 브라우저에만 저장되고 서버로 보내지 않아요. 데모에서 로그아웃하면 성향 진단 결과, 보유 종목, 관심 종목, 판단 메모를 이 브라우저에서 모두 지워요.
            </p>
          </Section>

          <Section id="keep" title="보관 기간과 삭제">
            <p className="m-0 text-sm text-body">
              계정을 삭제할 때까지 보관하고, 삭제하면 위 정보를 데이터베이스에서 바로 모두 지워요. 지운 정보는 되돌릴 수 없고, 사용자 정보는 따로 백업하지 않아요.
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

          <Section id="overseas" title="국외 이전">
            <p className="m-0 text-sm text-body">
              두 회사 모두 미국 회사라, 서비스 이용 계약을 이행하려고 처리를 맡기면서 정보가 국외로 이전될 수 있어요(개인정보 보호법 제28조의8 1항 3호).
            </p>
            <dl className="m-0 flex flex-col gap-4">
              <div className="flex flex-col gap-1">
                <dt className="text-base font-medium text-ink">Supabase, Inc. (미국)</dt>
                <dd className="m-0 text-sm text-body">이전 항목: 위 &apos;모으는 정보&apos; 전체. 저장 서버는 서울이고, 회사의 운영과 장애 대응 과정에서 미국에서 접근할 수 있어요.</dd>
                <dd className="m-0 text-xs text-muted">시기와 방법: 가입하고 저장할 때마다 암호화된 네트워크로. 보유 기간: 계정 삭제까지</dd>
              </div>
              <div className="flex flex-col gap-1">
                <dt className="text-base font-medium text-ink">Vercel Inc. (미국)</dt>
                <dd className="m-0 text-sm text-body">이전 항목: 접속 기록(IP 주소, 접속 시각, 브라우저 정보). 웹사이트 전송에 써요.</dd>
                <dd className="m-0 text-xs text-muted">시기와 방법: 접속할 때마다 암호화된 네트워크로. 보유 기간: Vercel 운영 기록 보관 기간</dd>
              </div>
            </dl>
            <p className="m-0 text-sm text-body">
              국외 이전을 원하지 않으면 가입하지 않고 데모로 둘러보거나, 계정을 삭제하면 돼요. 이때 계정 기능(저장)은 쓸 수 없어요.
            </p>
          </Section>

          <Section id="safety" title="안전하게 지키는 방법">
            <p className="m-0 text-sm text-body">
              비밀번호는 암호화해 저장하고, 모든 전송은 암호화된 연결(HTTPS)로 해요. 데이터베이스는 행 단위 접근 제한으로 내 계정의 정보만 읽고 쓸 수 있고, 관리 권한은 운영 팀원만 가져요.
            </p>
          </Section>

          <Section id="contact" title="문의">
            <p className="m-0 text-sm text-body">
              개인정보 보호 책임자: {SERVICE_NAME} 팀장, <a href={`mailto:${CONTACT}`} className="text-brand hover:underline">{CONTACT}</a>
            </p>
            <p className="m-0 text-sm text-body">열람, 정정, 삭제, 처리 정지를 요청하면 지체 없이 처리하고 결과를 알려 드려요.</p>
            <p className="m-0 text-sm text-body">처리방침을 바꾸면 시행일을 고치고 이 화면에 알려요. 이전 판은 2026년 10월 26일 시행이에요.</p>
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
