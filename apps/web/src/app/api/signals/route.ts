import { backend } from "@/lib/backend";
import { validOrigin } from "@/lib/access";

export async function GET(request: Request) {
  const params = new URL(request.url).searchParams;
  const id = params.get("id");
  if (id && !/^[a-f0-9]{64}$/.test(id))
    return Response.json({ error: "Invalid signal ID" }, { status: 422 });
  try {
    const response = await backend(id ? `/v1/signals/${id}` : "/v1/signals");
    return Response.json(await response.json(), { status: response.status });
  } catch {
    return Response.json({ error: "Signal API unavailable" }, { status: 503 });
  }
}

export async function POST(request: Request) {
  if (!validOrigin(request))
    return Response.json(
      { error: "Local same-origin request required" },
      { status: 403 },
    );
  try {
    const data = await request.json();
    if (typeof data.id !== "string" || !/^[a-f0-9]{64}$/.test(data.id))
      return Response.json({ error: "Invalid signal ID" }, { status: 422 });
    const response = await backend(`/v1/signals/${data.id}/slot`, {
      method: "POST",
      body: JSON.stringify({ action: data.action, note: data.note }),
    });
    return Response.json(await response.json(), { status: response.status });
  } catch {
    return Response.json(
      { error: "Could not update the signal slot" },
      { status: 503 },
    );
  }
}
