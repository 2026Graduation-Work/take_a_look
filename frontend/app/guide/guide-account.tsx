"use client";

import AccountControls from "../components/account-controls";
import { useOnboarding } from "../components/onboarding-provider";

export default function GuideAccount() {
  const { state } = useOnboarding();
  return state.status === "signed_out" ? null : <AccountControls />;
}
