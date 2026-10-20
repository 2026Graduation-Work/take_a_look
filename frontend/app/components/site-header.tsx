import Link from "next/link";
import AccountControls from "./account-controls";
import MarketStatusBar from "./market-status-bar";
import StockSearch from "./stock-search";
import type { InvestorProfileSummary, MarketStatus } from "@/lib/types";
import Wordmark from "@/components/brand/Wordmark";

interface SiteHeaderProps {
  profile: InvestorProfileSummary;
  marketStatus: MarketStatus;
  query?: string;
  onQueryChange?: (value: string) => void;
}

// 헤더: 로고(누르면 대시보드) + 이용 안내 + 검색 + 이름 ▾. 화면 이동 탭(대시보드, 보유 종목)은 두지 않는다(10/20 메뉴 정리).
// 보유 종목, 내 투자 성향, 계정 설정은 이름 메뉴에 있다. 390에서는 '이용 안내'도 이름 메뉴 맨 위로 간다
export default function SiteHeader({ query, onQueryChange, profile, marketStatus }: SiteHeaderProps) {
  return (
    <>
      <header className="glass-bar sticky top-0 z-50">
        <div className="mx-auto box-border flex min-h-14 w-full max-w-[1200px] flex-wrap items-center gap-x-5 gap-y-2 px-4 py-2 sm:h-14 sm:flex-nowrap sm:px-6 sm:py-0 lg:px-8">
          <Link href="/" aria-label="대시보드" className="flex min-h-11 flex-none items-center text-lg hover:no-underline">
            <Wordmark size={26} />
          </Link>
          <Link href="/guide" className="hidden min-h-11 flex-none items-center text-xs font-medium text-muted hover:text-ink hover:no-underline sm:flex">
            이용 안내
          </Link>

          {onQueryChange ? (
            <div className="order-last flex min-w-0 basis-full items-center sm:order-none sm:flex-1 sm:basis-auto sm:justify-end">
              <StockSearch query={query ?? ""} onQueryChange={onQueryChange} />
            </div>
          ) : null /* 검색이 없는 화면은 이름 메뉴가 ml-auto로 오른쪽 끝에 붙는다 */}

          <AccountControls profile={profile} />
        </div>
      </header>
      {/* 시장 바는 고정 영역 밖: 줄바꿈으로 높아져도(390·200% 확대) 스크롤하면 사라져 화면을 가리지 않는다(#305 후속) */}
      <MarketStatusBar status={marketStatus} />
    </>
  );
}
