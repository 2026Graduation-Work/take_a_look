import type { NextConfig } from "next";

// OCR 워커는 OpenCV가 new Function을 써서 'unsafe-eval'이 필요하다. 같은 출처 파일로 만든 워커는 자기 응답 헤더의 CSP를
// 따르므로 'unsafe-eval'은 /ocr/ 응답에만 준다. 화면 CSP는 처음 연 문서 것이 화면 이동 내내 쓰이므로 화면마다 다르게 두지 않는다.
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
      { source: "/ocr/v1/:file*", headers: [{ key: "Cache-Control", value: "public, max-age=31536000, immutable" }] },
    ];
  },
// /dev-ocr는 page의 notFound()만으로는 상태가 200으로 나가서(스트리밍) 운영에서는 없는 경로로 돌린다(404)
  async rewrites() {
    return dev ? [] : { beforeFiles: [{ source: "/dev-ocr", destination: "/_dev-only-not-found" }], afterFiles: [], fallback: [] };
  },
};

export default nextConfig;
