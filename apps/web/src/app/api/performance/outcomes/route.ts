import { backend } from "@/lib/backend";

export async function GET(request: Request) {
  const incoming = new URL(request.url).searchParams;
  const params = new URLSearchParams();
  for (const key of ["limit", "symbol", "direction", "setup_type", "strategy"]) {
    if (incoming.has(key)) params.set(key, incoming.get(key)!);
  }
  try {
    const response = await backend(`/v1/analytics/outcomes?${params}`);
    return Response.json(await response.json(), { status: response.status });
  } catch {
    return Response.json({ error: "Outcome analytics unavailable" }, { status: 503 });
  }
}
