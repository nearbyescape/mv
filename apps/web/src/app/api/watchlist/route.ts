import { backend } from "@/lib/backend";
import { validOrigin } from "@/lib/access";
export async function GET() {
  try {
    const r = await backend("/v1/watchlist");
    return Response.json(await r.json(), { status: r.status });
  } catch {
    return Response.json(
      { error: "API offline; selected coins cannot be loaded." },
      { status: 503 },
    );
  }
}
export async function PUT(request: Request) {
  // Only local, same-origin writes during this foundation. No public admin endpoint.
  if (!validOrigin(request))
    return Response.json(
      { error: "Local same-origin request required" },
      { status: 403 },
    );
  try {
    const data = await request.json();
    const r = await backend("/v1/watchlist", {
      method: "PUT",
      body: JSON.stringify(data),
    });
    return Response.json(await r.json(), { status: r.status });
  } catch {
    return Response.json(
      { error: "Could not save selected coins. Check the local API." },
      { status: 503 },
    );
  }
}
