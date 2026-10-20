"use client";

import AccountControls from "../components/account-controls";
import { useOnboarding } from "../components/onboarding-provider";

// 이용 안내는 로그인 없이도 열린다. 로그인 전에는 로고만, 로그인 뒤에는 다른 화면처럼 계정 메뉴를 붙인다
export default function GuideAccount() {
  const { state } = useOnboarding();
  return state.status === "signed_out" ? null : <AccountControls />;
}
