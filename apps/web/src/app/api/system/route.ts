import { backend } from "@/lib/backend";
export async function GET() {
  try {
    const response = await backend("/v1/operations/health");
    return Response.json(await response.json(), { status: response.status });
  } catch {
    return Response.json(
      {
        status: "offline",
        mode: "local-foundation",
        database: "unavailable",
        collector: {
          state: "unavailable",
          live: false,
          last_event_at: null,
          error: "API unavailable",
          clock_offset_ms: 0,
        },
        signals: "unavailable",
        engine: {
          state: "unavailable",
          running: false,
          ready: false,
          last_decision_at: null,
          error: "API unavailable",
        },
        telegram: "not-configured",
        ai: "not-configured",
      },
      { status: 503 },
    );
  }
}
