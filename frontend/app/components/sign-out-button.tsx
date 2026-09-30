"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { useOnboarding } from "./onboarding-provider";

export default function SignOutButton({ className, label }: { className?: string; label?: string } = {}) {
  const router = useRouter();
  const { state, logOut } = useOnboarding();
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  async function handleSignOut() {
    // 로그인 계정은 Supabase에 남으므로 묻지 않는다. 문구는 lib/auth.ts signOut이 실제로 지우는 것만 적는다.
    if (
      state.mode === "demo" &&
      !window.confirm(
        "데모에서 저장한 성향 진단 결과, 보유 종목, 관심 종목, 판단 메모가 이 브라우저에서 삭제돼요. 계속 쓰려면 이메일로 시작해 주세요.\n\n로그아웃할까요?",
      )
    ) return;
    setSubmitting(true);
    setError("");
    try {
      await logOut();
      router.replace("/login");
    } catch (signOutError) {
      setError(
        signOutError instanceof Error
          ? signOutError.message
          : "로그아웃하지 못했어요. 잠시 뒤 다시 눌러 주세요.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex items-center">
      <button
        type="button"
        onClick={() => void handleSignOut()}
        disabled={submitting}
        title={error || undefined}
        className={
          className ??
          "min-h-11 whitespace-nowrap text-xs font-medium text-body hover:text-ink disabled:cursor-not-allowed disabled:opacity-50"
        }
      >
        {submitting ? (
          "처리 중"
        ) : label ? (
          label
        ) : (
          <>
            <span className="sm:hidden">나가기</span>
            <span className="hidden sm:inline">로그아웃</span>
          </>
        )}
      </button>
      {error && (
        <span role="alert" className="sr-only">
          {error}
        </span>
      )}
    </div>
  );
}
