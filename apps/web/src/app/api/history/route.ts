import { backend } from "@/lib/backend";
export async function GET(request: Request) {
  const incoming = new URL(request.url).searchParams;
  const params = new URLSearchParams();
  for (const key of [
    "symbol",
    "direction",
    "date",
    "before_time",
    "before_id",
    "limit",
  ])
    if (incoming.has(key)) params.set(key, incoming.get(key)!);
  try {
    const r = await backend(`/v1/history/signals?${params}`);
    return Response.json(await r.json(), { status: r.status });
  } catch {
    return Response.json(
      { error: "Signal history unavailable" },
      { status: 503 },
    );
  }
}
