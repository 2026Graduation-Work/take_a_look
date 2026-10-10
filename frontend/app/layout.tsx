import type { Metadata, Viewport } from "next";
import localFont from "next/font/local";
import OnboardingProvider from "./components/onboarding-provider";
import { SERVICE_DESCRIPTION, SERVICE_NAME, SERVICE_TAGLINE } from "@/lib/brand";
import "./globals.css";

const pretendard = localFont({
  src: "./fonts/PretendardVariable.woff2",
  display: "swap",
  weight: "45 920",
  variable: "--font-pretendard",
});

// 아이폰 홈 인디케이터 영역(safe-area)까지 그려야 하단 탭 막대가 env(safe-area-inset-bottom)로 비켜 선다.
// theme-color = 페이지 바탕(--color-page). 모바일 브라우저 주소창 색이 화면과 이어진다(Vercel Web Interface Guidelines)
export const viewport: Viewport = { viewportFit: "cover", themeColor: "#f5f5f7" };

export const metadata: Metadata = {
  metadataBase: new URL("https://stock-prediction-v2-chi.vercel.app"),
  title: { default: SERVICE_NAME, template: `%s · ${SERVICE_NAME}` },
  description: SERVICE_DESCRIPTION,
  applicationName: SERVICE_NAME,
  openGraph: {
    type: "website",
    locale: "ko_KR",
    siteName: SERVICE_NAME,
    title: `${SERVICE_NAME} — ${SERVICE_TAGLINE}`,
    description: SERVICE_DESCRIPTION,
  },
  twitter: {
    card: "summary_large_image",
    title: `${SERVICE_NAME} — ${SERVICE_TAGLINE}`,
    description: SERVICE_DESCRIPTION,
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ko" className={`${pretendard.variable} h-full`}>
      <body className="min-h-full">
        <OnboardingProvider>{children}</OnboardingProvider>
      </body>
    </html>
  );
}
