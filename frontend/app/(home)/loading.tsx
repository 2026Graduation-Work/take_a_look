import { Bone, SkeletonPage } from "../components/skeleton";

// 대시보드 뼈대: 요약 문장 → 왼쪽 '내 포트폴리오', 오른쪽 '신호가 강한 종목'(1024px 이상 8:4)
export default function Loading() {
  return (
    <SkeletonPage label="대시보드를 불러오는 중이에요." width="full">
      <div className="flex flex-col gap-3">
        <Bone className="h-9 w-2/3 max-w-xl" />
        <Bone className="h-5 w-1/3 max-w-xs" />
      </div>
      <div className="grid grid-cols-1 items-start gap-12 lg:grid-cols-12 lg:gap-6">
        <div className="flex flex-col gap-6 lg:col-span-8">
          <Bone className="h-7 w-40" />
          <div aria-hidden className="surface h-72" />
          <div aria-hidden className="surface h-48" />
        </div>
        <div className="flex flex-col gap-6 lg:col-span-4">
          <Bone className="h-7 w-40" />
          <div aria-hidden className="surface h-96" />
        </div>
      </div>
    </SkeletonPage>
  );
}
