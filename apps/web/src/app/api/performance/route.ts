import { backend } from "@/lib/backend";

export async function GET() {
  try {
    const response = await backend("/v1/analytics/performance");
    return Response.json(await response.json(), { status: response.status });
  } catch {
    return Response.json({ error: "Performance analytics unavailable" }, { status: 503 });
  }
}
