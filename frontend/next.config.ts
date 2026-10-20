import type { NextConfig } from "next";

// 보안 헤더(docs/security/2026-10-audit.md). CSP는 nonce 없이 Next 인라인 스크립트를 허용하되, 외부 출처는 Supabase만 연다.
// 스크린샷 글자 읽기 도구(lib/holdings-ocr/recognize.ts)는 빌드 때 public/ocr/에 받아 같은 출처에서 준다.
// 그 워커는 OpenCV가 new Function을 써서 'unsafe-eval'이 필요하다. 같은 출처 파일로 만든 워커는 자기 응답 헤더의 CSP를
// 따르므로 'unsafe-eval'은 /ocr/ 응답에만 준다. 화면 CSP는 처음 연 문서 것이 화면 이동 내내 쓰이므로(#393 원인)
// 화면마다 다르게 두지 않는다.
const SUPABASE = process.env.NEXT_PUBLIC_SUPABASE_URL ?? "";
const dev = process.env.NODE_ENV !== "production";

const PAGE_CSP = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline' 'wasm-unsafe-eval'${dev ? " 'unsafe-eval'" : ""}`,
  "worker-src 'self'",
  `connect-src 'self' ${SUPABASE} ${SUPABASE.replace(/^https/, "wss")}${dev ? " ws:" : ""}`,
  "img-src 'self' data: blob:",
  "style-src 'self' 'unsafe-inline'",
  "font-src 'self' data:",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
].join("; ");
// 글자 읽기 워커(와 그 워커가 자기 파일로 만드는 하위 워커)용. 모델·wasm도 같은 출처에서 받는다.
// /ocr 아래 없는 주소의 404 문서도 이 CSP를 받으므로 문서용 지시어(base-uri, form-action, frame-ancestors)도 닫는다
const OCR_CSP =
  "default-src 'self'; script-src 'self' 'unsafe-eval' 'wasm-unsafe-eval'; worker-src 'self'; connect-src 'self' data:; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'";

const headers = (csp: string) => [
  { key: "Content-Security-Policy", value: csp },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), payment=(), usb=()" },
];

const nextConfig: NextConfig = {
  async headers() {
    // CSP 헤더가 둘이면 교집합이 되므로 한 경로에는 하나만 붙게 나눈다
    return [
      { source: "/:path((?!ocr/).*)", headers: headers(PAGE_CSP) },
      { source: "/ocr/:file*", headers: headers(OCR_CSP) },
    ];
  },
  // 개발용 /dev-ocr는 page의 notFound()만으로는 상태가 200으로 나가서(스트리밍) 운영에서는 없는 경로로 돌린다(404)
  async rewrites() {
    return dev ? [] : { beforeFiles: [{ source: "/dev-ocr", destination: "/_dev-only-not-found" }], afterFiles: [], fallback: [] };
  },
};

export default nextConfig;
