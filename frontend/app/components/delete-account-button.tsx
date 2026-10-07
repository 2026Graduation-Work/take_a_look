"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { deleteAccount } from "@/lib/auth";
import ConfirmButton from "./confirm-button";
import { useOnboarding } from "./onboarding-provider";

// 로그인 계정만. 데모는 로그아웃이 곧 브라우저 데이터 삭제다.
export default function DeleteAccountButton() {
  const router = useRouter();
  const { state, logOut } = useOnboarding();
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  if (state.mode !== "supabase" || state.status === "signed_out") return null;

  async function handleDelete() {
    setSubmitting(true);
    setError("");
    try {
      await deleteAccount();
      await logOut();
      router.replace("/login");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "계정을 삭제하지 못했어요. 잠시 뒤 다시 눌러 주세요.");
      setSubmitting(false);
    }
  }

  return (
    <div className="flex flex-col items-start gap-1">
      <ConfirmButton
        title="계정을 삭제할까요?"
        message="이메일·이름, 성향 진단 결과, 보유·관심 종목, 판단 메모가 모두 지워지고 되돌릴 수 없어요."
        confirmLabel="계정 삭제"
        onConfirm={() => void handleDelete()}
        disabled={submitting}
        className="btn-remove"
      >
        {submitting ? "삭제 중" : "계정 삭제"}
      </ConfirmButton>
      {error && <p role="alert" className="m-0 text-xs text-ink">{error}</p>}
    </div>
  );
}
