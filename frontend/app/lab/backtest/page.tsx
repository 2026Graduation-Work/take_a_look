import { notFound } from "next/navigation";
import Lab from "./lab";

export default function BacktestLabPage() {
  if (process.env.NODE_ENV === "production" || process.env.BACKTEST_LAB_ENABLED !== "1") notFound();
  return <Lab />;
}
