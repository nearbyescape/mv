import { backend } from "@/lib/backend";
export async function GET() {
  try {
    const response = await backend("/v1/paper");
    return Response.json(await response.json(), {
      status: response.status,
      headers: { "Cache-Control": "no-store" },
    });
  } catch {
    return Response.json(
      { error: "Forward paper API unavailable" },
      { status: 503 },
    );
  }
}
