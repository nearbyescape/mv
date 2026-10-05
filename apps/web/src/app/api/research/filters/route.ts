import { backend } from "@/lib/backend";

const files = [
  "report.json",
  "trades.csv",
  "trades.jsonl",
  "diagnostics.json",
  "dataset-manifest.json",
  "source-audit.json",
];
export async function GET(request: Request) {
  const file = new URL(request.url).searchParams.get("file");
  if (file && !files.includes(file))
    return Response.json({ error: "Unknown filter export" }, { status: 422 });
  try {
    const response = await backend(
      file
        ? `/v1/research/filters/export?file=${encodeURIComponent(file)}`
        : "/v1/research/filters",
    );
    if (!file || !response.ok)
      return Response.json(await response.json(), { status: response.status });
    return new Response(response.body, {
      headers: {
        "Content-Type":
          response.headers.get("content-type") || "application/octet-stream",
        "Content-Disposition": `attachment; filename="mv-filter-study-${file}"`,
        "Cache-Control": "no-store",
      },
    });
  } catch {
    return Response.json(
      { error: "Filter study API unavailable" },
      { status: 503 },
    );
  }
}
