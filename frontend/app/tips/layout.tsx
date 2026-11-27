import { Suspense, type ReactNode } from "react";
import BrandHeader from "@/app/components/brand-header";
import DisclaimerFooter from "@/app/components/disclaimer-footer";
import ReadingNavigation from "@/app/components/reading-navigation";
import GuideAccount from "@/app/guide/guide-account";
import { BEGINNER_TIPS } from "@/lib/beginner-tips";
import { topicForCategory } from "@/lib/tip-navigation";
import TipTopicNavigation from "./tip-topic-navigation";

const topicsById = Object.fromEntries(BEGINNER_TIPS.map(tip => [tip.id, topicForCategory(tip.category)]));

export default function TipsLayout({ children }: { children: ReactNode }) {
  return (
    <>
      <BrandHeader><GuideAccount /></BrandHeader>
      <ReadingNavigation current="tips" />
      <main className="page grid gap-6 pb-12 pt-6 lg:grid-cols-[200px_minmax(0,1fr)] lg:gap-8 lg:pt-8">
        <Suspense>
          <TipTopicNavigation topicsById={topicsById} />
        </Suspense>
        <div className="min-w-0 lg:col-start-2 lg:row-start-1">{children}</div>
      </main>
      <DisclaimerFooter fixed={false} />
    </>
  );
}
