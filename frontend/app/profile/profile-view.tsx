"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useSyncExternalStore } from "react";
import { ResultView } from "../survey/survey-flow";
import SiteHeader from "../components/site-header";
import DisclaimerFooter from "../components/disclaimer-footer";
import DeleteAccountButton from "../components/delete-account-button";
import SignOutButton from "../components/sign-out-button";
import { useOnboarding } from "../components/onboarding-provider";
import { getDashboardData } from "@/lib/queries";
import { summaryFromProfilingOutput } from "@/lib/profiling-rules";
import {
  getSavedProfileSnapshot,
  getServerProfileSnapshot,
  parseSavedProfile,
  subscribeToSavedProfile,
} from "@/lib/save-profile";

// 대시보드 맨 위 성향 한 줄을 누르면 오는 화면: 저장된 결과를 그대로 보여 주고, 다시 진단으로 이어진다.
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
      <main className="mx-auto flex w-full max-w-[720px] flex-col gap-8 px-4 py-8 sm:px-8">
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
        {/* 헤더 계정 메뉴 "계정 관리"가 여기로 온다. 계정 삭제는 로그인 계정만(데모에서는 DeleteAccountButton이 숨김). */}
        <section id="account" aria-labelledby="account-title" className="surface flex scroll-mt-40 flex-col items-start gap-4 px-6 py-7 sm:scroll-mt-20 sm:px-10">
          <h2 id="account-title" className="m-0 text-lg font-semibold text-ink">
            계정
          </h2>
          <div className="flex flex-col gap-1">
            {account.displayName && <p className="m-0 text-sm font-semibold text-ink">{account.displayName}</p>}
            <p className="m-0 text-sm text-body">{account.email ?? "데모 계정 · 이 브라우저에만 저장돼요"}</p>
          </div>
          <SignOutButton className="btn-text" label="로그아웃" />
          <DeleteAccountButton />
        </section>
      </main>
      <DisclaimerFooter fixed={false} />
    </div>
  );
}
