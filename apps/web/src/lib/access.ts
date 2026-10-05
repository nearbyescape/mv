import "server-only";
import { readFileSync } from "node:fs";

export const authRequired = () =>
  process.env.MV_ENVIRONMENT === "production" ||
  process.env.MV_AUTH_REQUIRED === "true";
export const cookieName = () =>
  process.env.MV_ENVIRONMENT === "production"
    ? "__Host-mv_session"
    : "mv_session";
export function serviceKey() {
  return process.env.MV_SERVICE_KEY_FILE
    ? readFileSync(process.env.MV_SERVICE_KEY_FILE, "utf8").trim()
    : process.env.MV_SERVICE_KEY || "";
}
export function validOrigin(request: Request) {
  const origin = request.headers.get("origin");
  if (process.env.MV_ENVIRONMENT === "production")
    return (
      origin === process.env.MV_PUBLIC_ORIGIN &&
      !!origin?.startsWith("https://")
    );
  const host = request.headers.get("host");
  return (
    !!host &&
    /^(127\.0\.0\.1|localhost):\d+$/.test(host) &&
    origin === `http://${host}`
  );
}
