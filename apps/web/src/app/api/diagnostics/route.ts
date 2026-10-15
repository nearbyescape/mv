import { backend } from "@/lib/backend";

// This is an authenticated, read-only operational view. Never persist or
// stage client messages from a status endpoint.
export async function GET() {
  try {
    const response = await backend("/v1/operations/diagnostics");
    return Response.json(await response.json(), {
      status: response.status,
      headers: { "Cache-Control": "no-store" },
    });
  } catch {
    return Response.json(
      {
        status: "UNAVAILABLE",
        v7_publication_authorized: false,
        v7_release_blockers: ["OPERATIONAL_DIAGNOSTICS_UNAVAILABLE"],
      },
      {
        status: 503,
        headers: { "Cache-Control": "no-store" },
      },
    );
  }
}
