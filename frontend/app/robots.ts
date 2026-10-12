import type { MetadataRoute } from "next";
import { SITE_URL } from "@/lib/brand";

// 개인 화면(보유·프로필·로그인)과 API는 검색에서 뺀다
export default function robots(): MetadataRoute.Robots {
  return {
    rules: { userAgent: "*", allow: "/", disallow: ["/api/", "/portfolio", "/profile", "/login"] },
    sitemap: `${SITE_URL}/sitemap.xml`,
  };
}
