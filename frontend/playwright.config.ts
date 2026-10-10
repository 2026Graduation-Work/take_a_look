import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: false,
  workers: 1,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI
    ? [["list"]]
    : [["list"], ["html", { open: "never" }]],
  outputDir: "test-results",
  use: {
    baseURL: "http://localhost:3101",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: [
    {
      command: "node tests/e2e/supabase-stub.mjs",
      url: "http://127.0.0.1:54321/rest/v1/health",
      reuseExistingServer: !process.env.CI,
    },
    {
      command: process.env.CI ? "pnpm start --port 3101" : "pnpm dev --port 3101",
      url: "http://localhost:3101/login",
      reuseExistingServer: false,
      timeout: 120_000,
      // 계정 화면 e2e용 가짜 Supabase 주소(위 stub + tests/e2e/supabase-mock.ts). CI는 빌드 때 같은 값을 넣는다.
      env: {
        NEXT_PUBLIC_SUPABASE_URL: "http://127.0.0.1:54321",
        NEXT_PUBLIC_SUPABASE_ANON_KEY: "e2e-anon-key",
        NEXT_PUBLIC_CHART_LOCAL_PREVIEW: "0",
      },
    },
  ],
});
