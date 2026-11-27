import type { Metadata } from "next";
import Link from "next/link";
import { BEGINNER_TIPS } from "@/lib/beginner-tips";
import { TIP_PAGE_SIZE, TIP_TOPICS, tipHref, tipPage, tipPageCount, tipReturnPath, tipTopic, type TipTopic } from "@/lib/tip-navigation";
import TipList from "./tip-list";

export const metadata: Metadata = { title: "투자 팁" };

export default async function TipsPage({ searchParams }: PageProps<"/tips">) {
  const query = await searchParams;
  const topic = tipTopic(query.category);
  const returnTo = tipReturnPath(query.returnTo);
  const tips = BEGINNER_TIPS.filter(tip => topic === "all" || tip.category === TIP_TOPICS[topic]);
  const page = tipPage(query.page, tips.length);
  const pageCount = tipPageCount(tips.length);
  const start = (page - 1) * TIP_PAGE_SIZE;
  const visibleTips = tips.slice(start, start + TIP_PAGE_SIZE).map(({ id, title, summary }) => ({
    id,
    title,
    summary,
    href: tipHref({ id, topic, returnTo }),
  }));

  return (
    <div className="page-narrow flex flex-col gap-6">
      <h1 className="m-0 text-3xl font-semibold">{topic === "all" ? "투자 팁" : TIP_TOPICS[topic]}</h1>
      {visibleTips.length ? <TipList tips={visibleTips} /> : <p className="m-0 text-sm text-body">이 주제에 팁이 없어요.</p>}
      {pageCount > 1 && <TipPagination page={page} pageCount={pageCount} topic={topic} returnTo={returnTo} />}
      {returnTo && (
        <Link href={returnTo} className="flex min-h-11 w-fit items-center text-sm underline underline-offset-2">
          원래 화면으로 돌아가기
        </Link>
      )}
    </div>
  );
}

function TipPagination({ page, pageCount, topic, returnTo }: {
  page: number;
  pageCount: number;
  topic: TipTopic;
  returnTo?: string;
}) {
  const control = "flex min-h-11 min-w-11 items-center justify-center rounded-md px-2 text-sm";
  const link = `${control} text-body hover:bg-track`;

  const previous = page > 1 ? (
    <Link href={tipHref({ topic, page: page - 1, returnTo })} rel="prev" aria-label="이전 페이지" className={link}>이전</Link>
  ) : (
    <span aria-disabled="true" className={`${control} text-muted`}>이전</span>
  );
  const next = page < pageCount ? (
    <Link href={tipHref({ topic, page: page + 1, returnTo })} rel="next" aria-label="다음 페이지" className={link}>다음</Link>
  ) : (
    <span aria-disabled="true" className={`${control} text-muted`}>다음</span>
  );
  const numbers = (
    <ul className="m-0 flex list-none flex-wrap justify-center gap-1 p-0">
      {Array.from({ length: pageCount }, (_, index) => index + 1).map(number => (
        <li key={number}>
          <Link
            href={tipHref({ topic, page: number, returnTo })}
            aria-label={`${number}페이지`}
            aria-current={page === number ? "page" : undefined}
            className={page === number ? `${control} bg-track font-semibold text-ink` : link}
          >
            {number}
          </Link>
        </li>
      ))}
    </ul>
  );

  return (
    <nav aria-label="투자 팁 페이지" className="tabular-nums">
      <div className="hidden items-center justify-center gap-1 sm:flex">
        {previous}
        {numbers}
        {next}
      </div>
      <div className="flex flex-col gap-2 sm:hidden">
        <div className="mx-auto max-w-48 min-[380px]:max-w-none">{numbers}</div>
        <div className="flex justify-center gap-2">{previous}{next}</div>
      </div>
    </nav>
  );
}
