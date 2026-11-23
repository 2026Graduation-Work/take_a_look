import type { MetadataRoute } from "next";
import { SITE_URL } from "@/lib/brand";
import { stockDetails } from "@/lib/mock-data";

export default function sitemap(): MetadataRoute.Sitemap {
  return ["", "/guide", "/privacy", "/survey", ...Object.keys(stockDetails).map((code) => `/stocks/${code}`)].map((path) => ({
    url: `${SITE_URL}${path}`,
  }));
}
