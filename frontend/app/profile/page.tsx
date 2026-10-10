import type { Metadata } from "next";
import ProfileView from "./profile-view";

export const metadata: Metadata = {
  title: "내 투자 성향",
};

export default function ProfilePage() {
  return <ProfileView />;
}
