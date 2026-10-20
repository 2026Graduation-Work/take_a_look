import AccountControls from "./account-controls";
import MarketStatusBar from "./market-status-bar";
import StockSearch from "./stock-search";
import type { InvestorProfileSummary, MarketStatus } from "@/lib/types";
import BrandHeader from "./brand-header";

interface SiteHeaderProps {
  profile: InvestorProfileSummary;
  marketStatus: MarketStatus;
  query?: string;
  onQueryChange?: (value: string) => void;
}

// 헤더: 로고(누르면 대시보드) + 검색 + 이름 ▾. 화면 이동 탭(대시보드, 보유 종목)은 두지 않는다(10/20 메뉴 정리).
// 보유 종목, 내 투자 성향, 이용 안내, 계정 설정은 이름 메뉴에 있다
export default function SiteHeader({ query, onQueryChange, profile, marketStatus }: SiteHeaderProps) {
  return (
    <>
      <BrandHeader>
        {onQueryChange ? (
            <div className="order-last flex min-w-0 basis-full items-center sm:order-none sm:flex-1 sm:basis-auto sm:justify-end">
            <StockSearch query={query ?? ""} onQueryChange={onQueryChange} />
          </div>
        ) : null /* 검색이 없는 화면은 이름 메뉴가 ml-auto로 오른쪽 끝에 붙는다 */}

        <AccountControls profile={profile} />
      </BrandHeader>
      {/* 시장 바는 고정 영역 밖: 줄바꿈으로 높아져도(390·200% 확대) 스크롤하면 사라져 화면을 가리지 않는다(#305 후속) */}
      <MarketStatusBar status={marketStatus} />
    </>
  );
}
