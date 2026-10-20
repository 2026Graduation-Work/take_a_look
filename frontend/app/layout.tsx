import type { Metadata, Viewport } from "next";
import localFont from "next/font/local";
import OnboardingProvider from "./components/onboarding-provider";
import { SERVICE_DESCRIPTION, SERVICE_NAME, SERVICE_TAGLINE, SITE_URL } from "@/lib/brand";
import "./globals.css";

const pretendard = localFont({
  src: "./fonts/PretendardVariable.woff2",
  display: "swap",
  weight: "45 920",
  variable: "--font-pretendard",
});

// viewportFit cover는 하단 탭 막대(지금은 없음) 때 넣은 설정이다. 지금 env(safe-area-inset-*)를 쓰는 곳은 없다.
// theme-color = 페이지 바탕(--color-page). 모바일 브라우저 주소창 색이 화면과 이어진다(Vercel Web Interface Guidelines)
export const viewport: Viewport = { viewportFit: "cover", themeColor: "#f5f5f7" };

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: { default: SERVICE_NAME, template: `%s - ${SERVICE_NAME}` },
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
