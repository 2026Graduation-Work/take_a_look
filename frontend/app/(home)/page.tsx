import Dashboard from "../components/dashboard";
import { getDashboardData } from "@/lib/queries";

export default function Home() {
  return <Dashboard {...getDashboardData()} />;
}
