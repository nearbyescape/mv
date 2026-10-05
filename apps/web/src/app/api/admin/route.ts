import { backend } from "@/lib/backend";
import { validOrigin } from "@/lib/access";
export async function GET(request: Request) {
  const section =
    new URL(request.url).searchParams.get("section") === "audit"
      ? "audit"
      : "users";
  try {
    const r = await backend(`/v1/admin/${section}`);
    return Response.json(await r.json(), { status: r.status });
  } catch {
    return Response.json(
      { error: "Administration unavailable" },
      { status: 503 },
    );
  }
}
async function write(request: Request, method: string) {
  if (!validOrigin(request))
    return Response.json(
      { error: "Same-origin request required" },
      { status: 403 },
    );
  try {
    const data = await request.json();
    if (
      method !== "POST" &&
      (typeof data.id !== "string" || !/^[a-f0-9-]{36,64}$/.test(data.id))
    )
      return Response.json(
        { error: "Invalid account identifier" },
        { status: 422 },
      );
    const path =
      method === "POST"
        ? "/v1/admin/invites"
        : method === "DELETE"
          ? `/v1/admin/invites/${data.id}`
          : `/v1/admin/users/${data.id}`;
    const r = await backend(path, {
      method,
      body: method === "DELETE" ? undefined : JSON.stringify(data),
    });
    return Response.json(await r.json(), {
      status: r.status,
      headers: { "Cache-Control": "no-store" },
    });
  } catch {
    return Response.json(
      { error: "Administration request failed" },
      { status: 503 },
    );
  }
}
export const POST = (request: Request) => write(request, "POST");
export const PATCH = (request: Request) => write(request, "PATCH");
export const DELETE = (request: Request) => write(request, "DELETE");
