import { notFound } from "next/navigation";
import Harness from "./harness";

// 개발용: 시험 화면(tests/fixtures/holdings-ocr)을 실제 인식 모듈로 읽어 결과를 돌려준다. 운영에는 없다.
export default function DevOcrPage() {
  if (process.env.NODE_ENV === "production") notFound();
  return <Harness />;
}
