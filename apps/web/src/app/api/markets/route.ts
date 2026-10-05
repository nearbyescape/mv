import { backend } from "@/lib/backend";
export async function GET(request: Request) {
  const url = new URL(request.url);
  const symbol = url.searchParams.get("symbol");
  const timeframe = url.searchParams.get("timeframe") || "1h";
  if (symbol && !/^[A-Z0-9]{2,20}USDT$/.test(symbol))
    return Response.json({ error: "Invalid market" }, { status: 422 });
  if (!["1h", "4h"].includes(timeframe))
    return Response.json({ error: "Invalid timeframe" }, { status: 422 });
  try {
    const response = await backend(
      symbol ? `/v1/markets/${symbol}?timeframe=${timeframe}` : "/v1/markets",
    );
    return Response.json(await response.json(), { status: response.status });
  } catch {
    return Response.json(
      {
        error:
          "Market API unavailable. Cached data must not be treated as fresh.",
      },
      { status: 503 },
    );
  }
}
