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
    const warning = state.mode === "demo" ? "이 기기에 저장한 데모 응답과 보유 종목이 지워져요. " : "";
    if (!window.confirm(`${warning}로그아웃할까요?`)) return;
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
