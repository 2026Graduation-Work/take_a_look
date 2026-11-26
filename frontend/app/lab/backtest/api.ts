const API = "/api/lab/backtest";

export async function read<T>(params?: URLSearchParams) {
  const response = await fetch(params ? `${API}?${params}` : API, { cache: "no-store" });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error ?? "데이터를 읽을 수 없습니다.");
  return data as T;
}

export async function act<T>(payload: unknown) {
  const response = await fetch(API, {
    method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(payload),
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error ?? "작업을 시작할 수 없습니다.");
  return result as T;
}

export const asMessage = (error: unknown) => error instanceof Error ? error.message : "작업을 완료하지 못했습니다.";
