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
      <main className="page pb-12 pt-6 lg:pt-8">
        <div className="page-narrow flex flex-col gap-6">
          <Suspense>
            <TipTopicNavigation topicsById={topicsById} />
          </Suspense>
          {children}
        </div>
      </main>
      <DisclaimerFooter fixed={false} />
    </>
  );
}
