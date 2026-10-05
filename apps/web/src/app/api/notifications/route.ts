import { backend } from "@/lib/backend";
import { validOrigin } from "@/lib/access";
export async function GET(request: Request) {
  const incoming = new URL(request.url).searchParams;
  const params = new URLSearchParams();
  for (const key of ["before_time", "before_id"])
    if (incoming.has(key)) params.set(key, incoming.get(key)!);
  try {
    const r = await backend(`/v1/notifications?${params}`);
    return Response.json(await r.json(), { status: r.status });
  } catch {
    return Response.json(
      { error: "Notification service unavailable" },
      { status: 503 },
    );
  }
}
export async function POST(request: Request) {
  if (!validOrigin(request))
    return Response.json(
      { error: "Same-origin request required" },
      { status: 403 },
    );
  try {
    const { id } = await request.json();
    if (typeof id !== "string" || !/^[a-f0-9-]{36}$/.test(id))
      return Response.json(
        { error: "Invalid notification identifier" },
        { status: 422 },
      );
    const r = await backend(`/v1/notifications/${id}/read`, { method: "POST" });
    return Response.json(await r.json(), { status: r.status });
  } catch {
    return Response.json(
      { error: "Notification update failed" },
      { status: 503 },
    );
  }
}
