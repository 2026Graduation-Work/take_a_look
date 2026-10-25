import Link from "next/link";
import { DISCLAIMER } from "@/lib/brand";

export default function DisclaimerFooter({ fixed = true }: { fixed?: boolean }) {
  return (
    <footer
      className={`${fixed ? "fixed inset-x-0 bottom-0 z-[60]" : "relative"} border-t border-line bg-white px-8 py-3 text-center`}
    >
      <span className="text-xs text-muted">{DISCLAIMER}</span>
      {/* 음수 여백: 누르는 영역만 44px로 넓히고 고정 푸터 높이는 그대로 둔다 */}
      <span className="-mt-2 -mb-3 flex justify-center gap-6">
        <Link href="/performance" className="flex min-h-11 w-fit items-center text-2xs text-muted underline underline-offset-2 hover:text-ink">
          모델 성적표
        </Link>
        <Link href="/privacy" className="flex min-h-11 w-fit items-center text-2xs text-muted underline underline-offset-2 hover:text-ink">
          개인정보 처리방침
        </Link>
      </span>
    </footer>
  );
}
