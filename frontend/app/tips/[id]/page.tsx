import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { BEGINNER_TIPS } from "@/lib/beginner-tips";
import { TIP_PAGE_SIZE, tipDetailTopic, tipHref, tipReturnPath, topicForCategory } from "@/lib/tip-navigation";

type TipPageProps = PageProps<"/tips/[id]">;

export async function generateMetadata({ params }: TipPageProps): Promise<Metadata> {
  const { id } = await params;
  const tip = BEGINNER_TIPS.find(item => item.id === id);
  return tip ? { title: tip.title, description: tip.summary } : { title: "투자 팁" };
}

export default async function TipDetailPage({ params, searchParams }: TipPageProps) {
  const [{ id }, query] = await Promise.all([params, searchParams]);
  const tip = BEGINNER_TIPS.find(item => item.id === id);
  if (!tip) notFound();
  const topic = tipDetailTopic(query.category, topicForCategory(tip.category));
  const returnTo = tipReturnPath(query.returnTo);
  const topicTips = topic === "all" ? BEGINNER_TIPS : BEGINNER_TIPS.filter(item => item.category === tip.category);
  const page = Math.floor(topicTips.indexOf(tip) / TIP_PAGE_SIZE) + 1;
  const listHref = `${tipHref({ topic, page, returnTo })}#tip-${id}`;

  return (
    <div className="page-narrow flex flex-col gap-6">
      <Link
        href={listHref}
        aria-label="투자 팁 목록"
        title="투자 팁 목록"
        className="flex size-11 items-center justify-center rounded-md bg-brand-soft text-brand hover:text-brand-deep"
      >
        <svg aria-hidden="true" viewBox="0 0 24 24" className="size-5" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <path d="m11 5-7 7 7 7M4 12h16" />
        </svg>
      </Link>
      <article aria-labelledby="tip-title" className="surface flex min-w-0 flex-col gap-6 p-4 wrap-anywhere sm:p-6">
        <header className="flex flex-col gap-2">
          <h1 id="tip-title" className="m-0 text-3xl font-semibold">{tip.title}</h1>
          <p className="m-0 text-sm text-body">{tip.summary}</p>
        </header>
        <section className="flex flex-col gap-2">
          <h2 className="m-0 text-xl font-semibold">왜 그럴까요?</h2>
          {tip.detail.map(line => <p key={line} className="m-0 text-sm text-body">{line}</p>)}
        </section>
        {tip.formula && (
          <section className="flex flex-col gap-2">
            <h2 className="m-0 text-xl font-semibold">계산으로 확인하기</h2>
            <p className="m-0 text-sm font-medium tabular-nums">{tip.formula}</p>
          </section>
        )}
        {tip.inService && (
          <section className="flex flex-col gap-2">
            <h2 className="m-0 text-xl font-semibold">어디서 확인할 수 있나요?</h2>
            <p className="m-0 text-sm text-body">{tip.inService}</p>
          </section>
        )}
        <section className="flex flex-col gap-2">
          <h2 className="m-0 text-xl font-semibold">출처와 확인 날짜</h2>
          <ul className="m-0 list-none p-0 text-xs text-muted">
            {tip.sources.map(source => (
              <li key={source.label}>
                {source.url ? (
                  <a href={source.url} className="flex min-h-11 w-fit items-center underline underline-offset-2">{source.label}</a>
                ) : source.label}
              </li>
            ))}
          </ul>
          <p className="m-0 text-xs text-muted">출처 확인 <time dateTime={tip.checkedAt}>{tip.checkedAt}</time></p>
          {tip.reviewBy && (
            <p className="m-0 text-xs text-muted">다음 확인 예정 <time dateTime={tip.reviewBy}>{tip.reviewBy}</time></p>
          )}
        </section>
      </article>
      {returnTo && (
        <Link href={returnTo} className="flex min-h-11 w-fit items-center text-sm underline underline-offset-2">
          원래 화면으로 돌아가기
        </Link>
      )}
    </div>
  );
}
