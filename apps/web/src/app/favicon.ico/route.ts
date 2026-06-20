export function GET() {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
    <rect width="64" height="64" rx="8" fill="#235789"/>
    <path d="M32 10l20 10v8c0 12-7.8 22.7-20 26-12.2-3.3-20-14-20-26v-8l20-10z" fill="#fff"/>
    <path d="M22 30h20M22 38h20M26 22h12" stroke="#235789" stroke-width="4" stroke-linecap="round"/>
  </svg>`;

  return new Response(svg, {
    headers: {
      "Content-Type": "image/svg+xml",
      "Cache-Control": "public, max-age=86400",
    },
  });
}
