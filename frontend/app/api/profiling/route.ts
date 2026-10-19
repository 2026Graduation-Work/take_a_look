// 설문 응답 → profiling_output 변환(결정론). 문항·채점 정본은 lib/profiling/, 변환 규칙은 lib/profiling-rules.ts.

import { NextResponse } from "next/server";
import { convertSurveyAnswers } from "@/lib/profiling-rules";

export async function POST(request: Request) {
  try {
    const answers: unknown = await request.json();
    return NextResponse.json(convertSurveyAnswers(answers));
  } catch (error) {
    const message =
      error instanceof Error ? error.message : "설문 응답을 변환하지 못했어요.";
    return NextResponse.json({ error: message }, { status: 400 });
  }
}
