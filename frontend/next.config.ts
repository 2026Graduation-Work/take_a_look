import type { NextConfig } from "next";

// 보안 헤더(docs/security/2026-10-audit.md). CSP는 nonce 없이 Next 인라인 스크립트를 허용하되, 외부 출처는
// Supabase와 스크린샷 글자 읽기 도구(lib/holdings-ocr/recognize.ts: jsDelivr 워커·wasm, Baidu 모델 저장소)만 연다.
// 글자 읽기 워커는 OpenCV가 new Function을 쓰고 자기 파일로 하위 워커를 만든다 → 'unsafe-eval'과 worker-src jsDelivr는
// 그 도구를 쓰는 화면(보유 종목, 설문의 보유 단계)에만 준다. 워커는 만든 화면의 CSP를 그대로 받는다.
const OCR_CDN = "https://cdn.jsdelivr.net";
const OCR_MODELS = "https://paddle-model-ecology.bj.bcebos.com";
const SUPABASE = process.env.NEXT_PUBLIC_SUPABASE_URL ?? "";
const dev = process.env.NODE_ENV !== "production";
const OCR_PAGES = ["/portfolio", "/survey"];

function csp(ocr: boolean) {
  return [
    "default-src 'self'",
    `script-src 'self' 'unsafe-inline' 'wasm-unsafe-eval'${ocr ? ` blob: ${OCR_CDN} 'unsafe-eval'` : dev ? " 'unsafe-eval'" : ""}`,
    `worker-src 'self' blob:${ocr ? ` ${OCR_CDN}` : ""}`,
    `connect-src 'self' ${SUPABASE} ${SUPABASE.replace(/^https/, "wss")}${ocr ? ` ${OCR_CDN} ${OCR_MODELS} data:` : ""}${dev ? " ws:" : ""}`,
    "img-src 'self' data: blob:",
    "style-src 'self' 'unsafe-inline'",
    "font-src 'self' data:",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
  ].join("; ");
}

const headers = (ocr: boolean) => [
  { key: "Content-Security-Policy", value: csp(ocr) },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), payment=(), usb=()" },
];

const nextConfig: NextConfig = {
  async headers() {
    // CSP 헤더가 둘이면 교집합이 되므로 한 경로에는 하나만 붙게 나눈다
    const ocr = OCR_PAGES.map((page) => page.slice(1)).join("|");
    return [
      { source: `/:path((?!(?:${ocr})(?:/|$)).*)`, headers: headers(false) },
      ...OCR_PAGES.flatMap((page) => [page, `${page}/:rest*`]).map((source) => ({ source, headers: headers(true) })),
    ];
  },
  // 개발용 /dev-ocr는 page의 notFound()만으로는 상태가 200으로 나가서(스트리밍) 운영에서는 없는 경로로 돌린다(404)
  async rewrites() {
    return dev ? [] : { beforeFiles: [{ source: "/dev-ocr", destination: "/_dev-only-not-found" }], afterFiles: [], fallback: [] };
  },
};

export default nextConfig;
