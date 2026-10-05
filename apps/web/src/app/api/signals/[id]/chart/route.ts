import { backend } from "@/lib/backend";
export async function GET(
  request: Request,
  context: { params: Promise<{ id: string }> },
) {
  const { id } = await context.params;
  const window = new URL(request.url).searchParams.get("window") || "source";
  if (!/^[a-f0-9]{64}$/.test(id) || !["source", "latest"].includes(window))
    return Response.json(
      { error: "Invalid signal chart request" },
      { status: 422 },
    );
  try {
    const response = await backend(`/v1/signals/${id}/chart?window=${window}`);
    return Response.json(await response.json(), { status: response.status });
  } catch {
    return Response.json(
      { error: "Signal chart unavailable" },
      { status: 503 },
    );
  }
}
