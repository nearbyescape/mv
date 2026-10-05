import { backend } from "@/lib/backend";

const exports = [
  "report.json",
  "trades.csv",
  "trades.jsonl",
  "diagnostics.json",
  "dataset-manifest.json",
  "source-audit.json",
];

export async function GET(request: Request) {
  const file = new URL(request.url).searchParams.get("file");
  if (file && !exports.includes(file))
    return Response.json(
      { error: "Unknown exit study export" },
      { status: 422 },
    );
  try {
    const response = await backend(
      file
        ? `/v1/research/study/export?file=${encodeURIComponent(file)}`
        : "/v1/research/study",
    );
    if (!file || !response.ok)
      return Response.json(await response.json(), { status: response.status });
    return new Response(response.body, {
      status: response.status,
      headers: {
        "Content-Type":
          response.headers.get("content-type") || "application/octet-stream",
        "Content-Disposition": `attachment; filename="mv-exit-study-${file}"`,
        "Cache-Control": "no-store",
      },
    });
  } catch {
    return Response.json(
      { error: "Exit study API unavailable" },
      { status: 503 },
    );
  }
}
