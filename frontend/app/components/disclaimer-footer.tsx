import Link from "next/link";
import { SERVICE_NAME } from "@/lib/brand";

export default function DisclaimerFooter({ fixed = true }: { fixed?: boolean }) {
  return (
    <footer
      className={`${fixed ? "fixed inset-x-0 bottom-0 z-[60]" : "relative"} border-t border-line bg-white px-8 py-3 text-center`}
    >
      <span className="text-xs text-muted">
        {SERVICE_NAME}은 투자 자문이 아니며, 제공되는 신호는 과거 데이터 기반의 통계적 참고
        정보입니다. 투자 판단과 책임은 투자자 본인에게 있습니다.
      </span>
      {/* 음수 여백: 누르는 영역만 44px로 넓히고 고정 푸터 높이는 그대로 둔다 */}
      <Link href="/performance" className="mx-auto -mt-2 -mb-3 flex min-h-11 w-fit items-center text-2xs text-muted underline underline-offset-2 hover:text-ink">
        모델 성적표
      </Link>
    </footer>
  );
}
