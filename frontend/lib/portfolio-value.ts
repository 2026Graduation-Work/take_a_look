export function holdingValue(holding: { quantity: number; avgBuyPrice: number }): number | null {
  const value = holding.quantity * holding.avgBuyPrice;
  return Number.isFinite(value) && value > 0 ? value : null;
}
