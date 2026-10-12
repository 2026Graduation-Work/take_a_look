import type { MetadataRoute } from "next";
import { SITE_URL } from "@/lib/brand";
import { stockDetails } from "@/lib/mock-data";

// 첫 화면·설문·데모 예시 종목만. 나머지 종목은 검색 로봇이 링크를 따라 찾는다
export default function sitemap(): MetadataRoute.Sitemap {
  return ["", "/survey", ...Object.keys(stockDetails).map((code) => `/stocks/${code}`)].map((path) => ({
    url: `${SITE_URL}${path}`,
  }));
}
