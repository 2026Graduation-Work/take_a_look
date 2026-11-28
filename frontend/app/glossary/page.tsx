import type { Metadata } from "next";
import BrandHeader from "@/app/components/brand-header";
import DisclaimerFooter from "@/app/components/disclaimer-footer";
import ReadingNavigation from "@/app/components/reading-navigation";
import GuideAccount from "@/app/guide/guide-account";
import { TERM_INFO } from "@/lib/copy-glossary";

export const metadata: Metadata = { title: "용어 모음" };

export default function GlossaryPage() {
  const terms = Object.values(TERM_INFO).sort((a, b) => a.label.localeCompare(b.label, "ko"));

  return (
    <>
      <BrandHeader><GuideAccount /></BrandHeader>
      <ReadingNavigation current="glossary" />
      <main className="page pb-12 pt-6 lg:pt-8">
        <div className="page-narrow flex flex-col gap-6">
          <h1 className="m-0 px-1 text-3xl font-semibold">용어 모음</h1>
          <dl className="surface m-0 flex flex-col gap-6 p-4 sm:p-6">
            {terms.map(term => (
              <div key={term.label} className="flex flex-col gap-2">
                <dt className="text-xl font-semibold text-ink">{term.label}</dt>
                <dd className="m-0 text-sm text-body">{term.define} {term.read}</dd>
              </div>
            ))}
          </dl>
        </div>
      </main>
      <DisclaimerFooter fixed={false} />
    </>
  );
}
