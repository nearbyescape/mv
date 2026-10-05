import { backend } from "@/lib/backend";

export async function GET(request: Request) {
  const file = new URL(request.url).searchParams.get("file");
  if (
    file &&
    ![
      "report.json",
      "trades.csv",
      "trades.jsonl",
      "dataset-manifest.json",
      "source-audit.json",
    ].includes(file)
  )
    return Response.json({ error: "Unknown research export" }, { status: 422 });
  try {
    const response = await backend(
      file
        ? `/v1/research/export?file=${encodeURIComponent(file)}`
        : "/v1/research",
    );
    if (!file || !response.ok)
      return Response.json(await response.json(), { status: response.status });
    return new Response(response.body, {
      status: response.status,
      headers: {
        "Content-Type":
          response.headers.get("content-type") || "application/octet-stream",
        "Content-Disposition": `attachment; filename="mv-research-${file}"`,
        "Cache-Control": "no-store",
      },
    });
  } catch {
    return Response.json(
      { error: "Research API unavailable" },
      { status: 503 },
    );
  }
}
