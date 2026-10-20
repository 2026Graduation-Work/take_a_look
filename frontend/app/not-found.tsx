import Link from "next/link";
import BrandHeader from "./components/brand-header";

// 없는 주소·없는 종목 코드(/stocks/999999)에서 보이는 화면. Next 기본 화면은 영어이고 돌아갈 길이 없었다(페르소나 워크스루 2026-10).
export default function NotFound() {
  return (
    <>
      <BrandHeader />
      <main className="mx-auto flex min-h-[70vh] w-full max-w-[480px] flex-col items-center justify-center gap-4 px-4 text-center">
        <h1 className="text-2xl font-semibold">찾는 화면이 없어요</h1>
        <p className="m-0 text-sm text-body">주소가 바뀌었거나, 지금 보여 드리지 않는 종목이에요. 코스피 종목만 볼 수 있어요.</p>
        <Link href="/" className="btn-primary">대시보드로 가기</Link>
      </main>
    </>
  );
}
