import { Bone, SkeletonPage } from "@/app/components/skeleton";

// 종목 상세 뼈대: 헤더(이름, 가격) → 한눈에 보기(차트) → 판단 근거 탭
export default function Loading() {
  return (
    <SkeletonPage label="종목 정보를 불러오는 중이에요." width="wide">
      <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-3 px-1">
        <div className="flex flex-col gap-2">
          <Bone className="h-4 w-24" />
          <Bone className="h-9 w-48" />
          <Bone className="h-5 w-32" />
        </div>
        <Bone className="h-10 w-40" />
      </div>
      <div className="surface flex flex-col gap-4 p-6">
        <Bone className="h-7 w-56" />
        <Bone className="h-5 w-3/4" />
        <Bone className="h-60" />
      </div>
      <div className="surface flex flex-col gap-4 p-6">
        <Bone className="h-9 w-full max-w-md" />
        <Bone className="h-40" />
      </div>
    </SkeletonPage>
  );
}
