"use client";

import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { TIP_TOPICS, tipDetailTopic, tipHref, tipReturnPath, tipTopic, type TipTopic } from "@/lib/tip-navigation";

// 11/28: 왼쪽 주제 칸이 제목을 밀어 용어 모음, 이용 안내와 시작선이 달라서 모든 폭에서 제목 위 칩 한 줄로 둔다
export default function TipTopicNavigation({ topicsById }: { topicsById: Readonly<Record<string, TipTopic>> }) {
  const { id } = useParams<{ id?: string }>();
  const query = useSearchParams();
  const itemTopic = id && Object.hasOwn(topicsById, id) ? topicsById[id] : undefined;
  const topic = itemTopic ? tipDetailTopic(query.get("category"), itemTopic) : tipTopic(query.get("category"));
  const returnTo = tipReturnPath(query.get("returnTo"));

  return (
    <nav aria-label="알고 계셨나요? 주제">
      <ul className="m-0 flex list-none gap-1 overflow-x-auto p-0 [scrollbar-width:none] sm:gap-2">
        {(Object.keys(TIP_TOPICS) as TipTopic[]).map(key => (
          <li key={key}>
            <Link
              href={tipHref({ topic: key, returnTo })}
              aria-current={key === topic ? "true" : undefined}
              className={`flex min-h-11 items-center whitespace-nowrap rounded-md px-3 text-sm ${key === topic ? "bg-brand-soft font-semibold text-brand" : "text-body hover:bg-field"}`}
            >
              {TIP_TOPICS[key]}
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}
