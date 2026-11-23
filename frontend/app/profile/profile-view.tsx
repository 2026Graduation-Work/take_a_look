"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useSyncExternalStore } from "react";
import { ResultView } from "../survey/survey-flow";
import SiteHeader from "../components/site-header";
import DisclaimerFooter from "../components/disclaimer-footer";
import DeleteAccountButton from "../components/delete-account-button";
import { useOnboarding } from "../components/onboarding-provider";
import { getDashboardData } from "@/lib/queries";
import { summaryFromProfilingOutput } from "@/lib/profiling-rules";
import {
  getSavedProfileSnapshot,
  getServerProfileSnapshot,
  parseSavedProfile,
  subscribeToSavedProfile,
} from "@/lib/save-profile";

export default function ProfileView() {
  const router = useRouter();
  const { state: account } = useOnboarding();
  const { profile: fallback, marketStatus } = getDashboardData();
  const saved = parseSavedProfile(
    useSyncExternalStore(subscribeToSavedProfile, getSavedProfileSnapshot, getServerProfileSnapshot),
  );
  const profile = saved ? summaryFromProfilingOutput(saved, fallback) : fallback;

  return (
    <div className="w-full">
      <SiteHeader profile={profile} marketStatus={marketStatus} />
      <main className="page pb-12 pt-6">
      <div className="page-narrow flex flex-col gap-12">
        {saved?.style_axes ? (
          <ResultView
            result={saved}
            readOnly
            nextLabel="다시 진단"
            onConfirm={() => router.push("/survey")}
            onBack={() => router.push("/")}
          />
        ) : (
          <section className="surface flex flex-col items-start gap-4 px-6 py-8">
            <p className="m-0 text-sm text-body">저장된 성향 결과가 없어요.</p>
            <Link href="/survey" className="btn-primary">
              성향 진단하기
            </Link>
          </section>
        )}
        <section id="account" aria-labelledby="account-title" className="surface flex scroll-mt-40 flex-col items-start gap-4 px-6 py-7 sm:scroll-mt-20 sm:px-10">
          <h2 id="account-title" className="m-0 text-lg font-semibold text-ink">
            계정 설정
          </h2>
          <div className="flex flex-col gap-1">
            {account.displayName && <p className="m-0 text-sm font-semibold text-ink">{account.displayName}</p>}
            <p className="m-0 text-sm text-body">{account.email ?? "데모 계정이라 이 브라우저에만 저장돼요."}</p>
          </div>
          <DeleteAccountButton />
        </section>
      </div>
      </main>
      <DisclaimerFooter fixed={false} />
    </div>
  );
}
