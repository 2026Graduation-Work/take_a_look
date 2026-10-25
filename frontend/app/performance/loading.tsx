import { Bone, SkeletonPage } from "../components/skeleton";

// 모델 성적표 뼈대: 제목과 결론 → 표 → 실험 설계
export default function Loading() {
  return (
    <SkeletonPage label="모델 성적표를 불러오는 중이에요." width="narrow">
      <div className="flex flex-col gap-3">
        <Bone className="h-9 w-48" />
        <Bone className="h-5 w-full" />
        <Bone className="h-5 w-2/3" />
      </div>
      <div aria-hidden className="surface h-64" />
      <div aria-hidden className="surface h-48" />
    </SkeletonPage>
  );
}
