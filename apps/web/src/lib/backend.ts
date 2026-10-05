import "server-only";
import { cookies, headers } from "next/headers";
import { authRequired, cookieName, serviceKey } from "./access";

export async function backend(path: string, init?: RequestInit) {
  const address = process.env.MV_API_URL || "http://127.0.0.1:8000";
  const url = new URL(address);
  if (
    ![
      "localhost",
      "127.0.0.1",
      ...(process.env.MV_ENVIRONMENT === "production" ? ["api"] : []),
    ].includes(url.hostname) ||
    !["http:", "https:"].includes(url.protocol) ||
    url.username ||
    url.password ||
    url.pathname !== "/" ||
    url.search ||
    url.hash
  )
    throw new Error("API must use the configured private gateway address");
  const token = authRequired()
    ? (await cookies()).get(cookieName())?.value || ""
    : process.env.MV_DEV_API_TOKEN || "mv-local-preview-only";
  const key = serviceKey();
  if (
    process.env.MV_ENVIRONMENT === "production" &&
    (key.length < 32 || !process.env.MV_PUBLIC_ORIGIN?.startsWith("https://"))
  )
    throw new Error("Production gateway configuration is incomplete");
  if (
    authRequired() &&
    !token &&
    !["/v1/auth/login", "/v1/auth/accept"].includes(path)
  )
    return Response.json({ detail: "Sign in required" }, { status: 401 });
  return fetch(`${address}${path}`, {
    ...init,
    cache: "no-store",
    signal: AbortSignal.timeout(8000),
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
      "X-MV-Service-Key": key,
      "X-MV-Client-IP": (await headers()).get("x-mv-client-ip") || "unknown",
      ...init?.headers,
    },
  });
}
