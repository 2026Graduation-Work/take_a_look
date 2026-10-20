import Link from "next/link";
import type { ReactNode } from "react";
import Wordmark from "@/components/brand/Wordmark";

// 모든 화면이 쓰는 헤더 틀: 로고(누르면 대시보드) 크기, 간격, 높이, 위치를 한 곳에서 정한다(10/20 헤더 통일).
// 로그인 전 화면(로그인, 이용 안내, 오류)은 로고만, 나머지는 children으로 검색, 계정 메뉴 등을 붙인다.
// 390에서 한 줄에 다 안 들어가면 basis-full 칸이 둘째 줄로 내려가고 로고 줄 높이는 그대로다
export default function BrandHeader({ children }: { children?: ReactNode }) {
  return (
    <header className="glass-bar sticky top-0 z-50">
      <div className="page flex min-h-14 flex-wrap items-center gap-x-5 gap-y-2 py-2 sm:h-14 sm:flex-nowrap sm:py-0">
        <Link href="/" aria-label="대시보드" className="flex min-h-11 flex-none items-center text-lg hover:no-underline">
          <Wordmark size={26} />
        </Link>
        {children}
      </div>
    </header>
  );
}
