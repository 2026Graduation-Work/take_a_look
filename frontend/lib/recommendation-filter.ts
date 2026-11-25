export interface HardConstraints {
  // 이 등급보다 위험한 종목을 뺀다. 설정한 적이 없으면 null.
  userMaxRiskTier: number | null;
  avoided: ReadonlySet<string>;
}

export function passesHardConstraints(
  riskGrade: number,
  riskFlags: readonly string[],
  constraints: HardConstraints,
): boolean {
  if (constraints.userMaxRiskTier !== null && riskGrade < constraints.userMaxRiskTier) return false;
  return !riskFlags.some((flag) => constraints.avoided.has(flag));
}

export function holdingAlertsOutside<T extends { code: string }>(
  alerts: readonly T[],
  recommended: readonly { code: string }[],
): T[] {
  const recommendedCodes = new Set(recommended.map(({ code }) => code));
  return alerts.filter(({ code }) => !recommendedCodes.has(code));
}
