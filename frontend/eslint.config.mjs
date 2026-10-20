import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
    // Playwright 실행 결과물(gitignore)
    "playwright-report/**",
    "test-results/**",
    // 빌드 때 받는 글자 읽기 도구(scripts/fetch-ocr-assets.mjs, gitignore)
    "public/ocr/**",
  ]),
]);

export default eslintConfig;
