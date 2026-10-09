"use client";

import { useState, type FormEvent } from "react";
import { useOnboarding } from "@/app/components/onboarding-provider";
import {
  signInWithPassword,
  signUpWithPassword,
  startDemoSession,
} from "@/lib/auth";
import { isSupabaseConfigured } from "@/lib/supabase";
import StepNav from "@/app/components/step-nav";
import Wordmark from "@/components/brand/Wordmark";
import { SERVICE_TAGLINE } from "@/lib/brand";

type AccountTab = "signin" | "signup";

export default function LoginForm() {
  const { refresh } = useOnboarding();
  // 이메일 계정 기능은 Supabase 환경변수가 있을 때만. 데모 계정은 항상 쓸 수 있다.
  const accountAvailable = isSupabaseConfigured();
  const [tab, setTab] = useState<AccountTab>("signin");
  const [emailOpen, setEmailOpen] = useState(false);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  async function run(task: () => Promise<void>) {
    setSubmitting(true);
    setError("");
    setNotice("");
    try {
      await task();
    } catch (taskError) {
      setError(taskError instanceof Error ? taskError.message : "요청을 처리하지 못했어요. 잠시 뒤 다시 눌러 주세요.");
    } finally {
      setSubmitting(false);
    }
  }

  function submitAccount(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void run(async () => {
      if (tab === "signin") {
        await signInWithPassword(email.trim(), password);
        await refresh(true);
        return;
      }
      const { needsEmailConfirmation } = await signUpWithPassword(email.trim(), password, name.trim());
      if (needsEmailConfirmation) {
        setNotice(`${email.trim()}로 확인 메일을 보냈어요. 메일의 링크를 누르면 로그인됩니다.`);
        return;
      }
      await refresh(true);
    });
  }

  function startDemo() {
    void run(async () => {
      startDemoSession();
      await refresh(true);
    });
  }

  const field =
    "h-11 w-full rounded-md bg-field px-4 text-sm font-normal text-ink outline-none focus:bg-white focus:ring-2 focus:ring-brand/30";

  function back() {
    setEmailOpen(false);
    setError("");
    setNotice("");
  }

  return (
    <main className="grid min-h-dvh place-items-center bg-page px-4 py-10">
      <section className="surface flex w-full max-w-[400px] flex-col gap-6 px-6 py-9 sm:px-9">
        <div className="flex flex-col items-center gap-3 text-center">
          <Wordmark size={36} className="text-2xl" />
          {emailOpen ? (
            <h1 className="text-3xl font-semibold">{tab === "signin" ? "로그인" : "회원가입"}</h1>
          ) : (
            <>
              <h1 className="sr-only">Take a Look 시작</h1>
              <p className="m-0 text-sm text-body">{SERVICE_TAGLINE}</p>
            </>
          )}
        </div>

        {emailOpen ? (
          <form onSubmit={submitAccount} className="flex flex-col gap-4">
            <div role="tablist" aria-label="계정" className="segmented grid grid-cols-2">
              {(
                [
                  ["signin", "로그인"],
                  ["signup", "회원가입"],
                ] as const
              ).map(([id, label]) => (
                <button
                  key={id}
                  type="button"
                  role="tab"
                  aria-selected={tab === id}
                  onClick={() => {
                    setTab(id);
                    setError("");
                    setNotice("");
                  }}
                >
                  {label}
                </button>
              ))}
            </div>
            {tab === "signup" && (
              <label className="flex flex-col gap-2 text-xs text-muted">
                이름
                <input
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  placeholder="화면 오른쪽 위에 보일 이름"
                  autoComplete="name"
                  maxLength={20}
                  required
                  autoFocus
                  className={field}
                />
              </label>
            )}
            <label className="flex flex-col gap-2 text-xs text-muted">
              이메일
              <input
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                placeholder="name@example.com"
                autoComplete="email"
                required
                autoFocus={tab === "signin"}
                className={field}
              />
            </label>
            <label className="flex flex-col gap-2 text-xs text-muted">
              비밀번호
              <input
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                placeholder={tab === "signup" ? "8자 이상" : ""}
                autoComplete={tab === "signup" ? "new-password" : "current-password"}
                minLength={tab === "signup" ? 8 : undefined}
                required
                className={field}
              />
            </label>
            {tab === "signup" && (
              <p className="m-0 text-2xs leading-5 text-muted">
                가입하면 이메일·이름, 성향 진단 결과, 보유·관심 종목, 판단 메모를 서울 리전 서버에 저장해요. 내 계정으로만
                읽고 쓸 수 있고, 판단 근거를 보여 주는 데에만 써요.
              </p>
            )}
            <Messages notice={notice} error={error} />
            <StepNav
              className="pt-2"
              onBack={back}
              backLabel="뒤로"
              backDisabled={submitting}
              nextType="submit"
              nextLabel={submitting ? "처리 중" : tab === "signin" ? "로그인" : "가입하고 시작"}
              nextDisabled={submitting}
            />
          </form>
        ) : (
          <div className="flex flex-col gap-3">
            {accountAvailable ? (
              <button type="button" onClick={() => setEmailOpen(true)} className="btn-primary w-full">
                이메일로 시작
              </button>
            ) : (
              <p className="m-0 rounded-md bg-field px-4 py-3 text-xs text-muted">
                이 배포에는 계정 기능이 아직 연결되지 않았어요. 데모로 모든 화면을 둘러볼 수 있어요.
              </p>
            )}
            <button type="button" onClick={startDemo} disabled={submitting} className="btn-secondary w-full">
              데모로 둘러보기
            </button>
            <Messages notice={notice} error={error} />
          </div>
        )}
      </section>
    </main>
  );
}

function Messages({ notice, error }: { notice: string; error: string }) {
  return (
    <>
      {notice && (
        <p role="status" className="m-0 rounded-md bg-field px-4 py-3 text-sm text-body">
          {notice}
        </p>
      )}
      {error && (
        <p role="alert" className="m-0 text-sm text-danger">
          {error}
        </p>
      )}
    </>
  );
}
