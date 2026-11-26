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
  rotateQuotesOnMobile?: boolean;
}

export default function SiteHeader({ query, onQueryChange, profile, marketStatus, rotateQuotesOnMobile }: SiteHeaderProps) {
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
      <MarketStatusBar status={marketStatus} rotateQuotesOnMobile={rotateQuotesOnMobile} />
    </>
  );
}
