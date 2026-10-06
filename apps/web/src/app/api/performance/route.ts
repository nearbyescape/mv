import { backend } from "@/lib/backend";

export async function GET(request: Request) {
  const incoming = new URL(request.url).searchParams;
  const params = new URLSearchParams();
  if (incoming.has("strategy")) params.set("strategy", incoming.get("strategy")!);
  try {
    const suffix = params.size ? `?${params}` : "";
    const response = await backend(`/v1/analytics/performance${suffix}`);
    return Response.json(await response.json(), { status: response.status });
  } catch {
    return Response.json({ error: "Performance analytics unavailable" }, { status: 503 });
  }
}
