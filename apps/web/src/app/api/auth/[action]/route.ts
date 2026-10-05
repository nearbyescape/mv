import { NextResponse } from "next/server";
import { backend } from "@/lib/backend";
import { validOrigin, cookieName } from "@/lib/access";

export async function GET(
  request: Request,
  context: { params: Promise<{ action: string }> },
) {
  const { action } = await context.params;
  if (action !== "me")
    return Response.json({ error: "Unknown account action" }, { status: 404 });
  try {
    const r = await backend("/v1/auth/me");
    return Response.json(await r.json(), {
      status: r.status,
      headers: { "Cache-Control": "no-store" },
    });
  } catch {
    return Response.json({ error: "Account API unavailable" }, { status: 503 });
  }
}
export async function POST(
  request: Request,
  context: { params: Promise<{ action: string }> },
) {
  if (!validOrigin(request))
    return Response.json(
      { error: "Same-origin request required" },
      { status: 403 },
    );
  const { action } = await context.params;
  if (!["login", "accept", "logout", "password"].includes(action))
    return Response.json({ error: "Unknown account action" }, { status: 404 });
  try {
    const body = action === "logout" ? {} : await request.json();
    const r = await backend(`/v1/auth/${action}`, {
      method: "POST",
      body: JSON.stringify(body),
    });
    const data = await r.json();
    const { token, ...visible } = data;
    const response = NextResponse.json(visible, {
      status: r.status,
      headers: { "Cache-Control": "no-store" },
    });
    if (r.ok && token)
      response.cookies.set(cookieName(), token, {
        httpOnly: true,
        secure: process.env.MV_ENVIRONMENT === "production",
        sameSite: "strict",
        path: "/",
        expires: new Date(data.expires_at),
      });
    if (action === "logout")
      response.cookies.set(cookieName(), "", {
        httpOnly: true,
        secure: process.env.MV_ENVIRONMENT === "production",
        sameSite: "strict",
        path: "/",
        maxAge: 0,
      });
    return response;
  } catch {
    if (action === "logout") {
      const response = NextResponse.json({ signed_out: true, server_revoked: false }, { status: 503 });
      response.cookies.set(cookieName(), "", {httpOnly: true, secure: process.env.MV_ENVIRONMENT === "production", sameSite: "strict", path: "/", maxAge: 0});
      return response;
    }
    return Response.json(
      { error: "Account service unavailable" },
      { status: 503 },
    );
  }
}
