"use client";

import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { TIP_TOPICS, tipDetailTopic, tipHref, tipReturnPath, tipTopic, type TipTopic } from "@/lib/tip-navigation";

export default function TipTopicNavigation({ topicsById }: { topicsById: Readonly<Record<string, TipTopic>> }) {
  const { id } = useParams<{ id?: string }>();
  const query = useSearchParams();
  const router = useRouter();
  const itemTopic = id && Object.hasOwn(topicsById, id) ? topicsById[id] : undefined;
  const topic = itemTopic ? tipDetailTopic(query.get("category"), itemTopic) : tipTopic(query.get("category"));
  const returnTo = tipReturnPath(query.get("returnTo"));
  const topics = Object.keys(TIP_TOPICS) as TipTopic[];

  return (
    <nav aria-label="알고 계셨나요? 주제" className="min-w-0 lg:col-start-1 lg:row-start-1">
      <form
        action="/tips"
        className="flex items-end gap-2 lg:hidden"
        onSubmit={event => {
          event.preventDefault();
          const selected = tipTopic(new FormData(event.currentTarget).get("category"));
          router.push(tipHref({ topic: selected, returnTo }));
        }}
      >
        <label className="flex min-w-0 flex-1 flex-col gap-2 text-xs font-medium text-body">
          주제
          <select
            key={`${id ?? "list"}:${topic}`}
            name="category"
            defaultValue={topic}
            className="min-h-11 w-full rounded-md bg-surface px-3 text-sm text-ink"
          >
            {topics.map(key => <option key={key} value={key}>{TIP_TOPICS[key]}</option>)}
          </select>
        </label>
        {returnTo && <input type="hidden" name="returnTo" value={returnTo} />}
        <button type="submit" className="btn-secondary">목록 보기</button>
      </form>
      <div className="hidden flex-col gap-2 lg:flex">
        <h2 className="m-0 text-xl font-semibold">주제</h2>
        <ul className="m-0 list-none p-0">
          {topics.map(key => (
            <li key={key}>
              <Link
                href={tipHref({ topic: key, returnTo })}
                aria-current={key === topic ? "true" : undefined}
                className={`flex min-h-11 items-center rounded-md px-3 text-sm ${key === topic ? "bg-track font-semibold text-ink" : "text-body hover:bg-field"}`}
              >
                {TIP_TOPICS[key]}
              </Link>
            </li>
          ))}
        </ul>
      </div>
    </nav>
  );
}
