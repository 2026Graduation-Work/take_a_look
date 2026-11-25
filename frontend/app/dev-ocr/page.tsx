import { notFound } from "next/navigation";
import Harness from "./harness";

export default function DevOcrPage() {
  if (process.env.NODE_ENV === "production") notFound();
  return <Harness />;
}
