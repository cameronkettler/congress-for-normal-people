import type { MetadataRoute } from "next";

const siteUrl = "https://congress-for-normal-people.com";

export default function sitemap(): MetadataRoute.Sitemap {
  const lastModified = new Date();

  return [
    {
      url: siteUrl,
      lastModified,
      changeFrequency: "weekly",
      priority: 1,
    },
    {
      url: `${siteUrl}/representatives`,
      lastModified,
      changeFrequency: "monthly",
      priority: 0.7,
    },
  ];
}
