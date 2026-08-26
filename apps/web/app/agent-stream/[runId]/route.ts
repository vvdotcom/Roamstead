export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET(
  request: Request,
  { params }: { params: Promise<{ runId: string }> },
) {
  const { runId } = await params;
  const apiUrl = process.env.API_URL ?? "http://127.0.0.1:8000";
  const after = new URL(request.url).searchParams.get("after") ?? "0";
  const lastEventId = request.headers.get("last-event-id");
  const upstream = await fetch(`${apiUrl}/api/v1/decision-briefs/${encodeURIComponent(runId)}/events?after=${encodeURIComponent(after)}`, {
    cache: "no-store",
    headers: {
      Accept: "text/event-stream",
      "Accept-Encoding": "identity",
      ...(lastEventId ? { "Last-Event-ID": lastEventId } : {}),
    },
    signal: request.signal,
  });

  if (!upstream.ok || !upstream.body) {
    return new Response(await upstream.text(), {
      status: upstream.status,
      headers: { "Content-Type": upstream.headers.get("Content-Type") ?? "text/plain" },
    });
  }

  return new Response(upstream.body, {
    status: upstream.status,
    headers: {
      "Content-Type": "text/event-stream; charset=utf-8",
      "Cache-Control": "no-cache, no-transform",
      "Content-Encoding": "identity",
      "Connection": "keep-alive",
      "X-Accel-Buffering": "no",
      "X-Content-Type-Options": "nosniff",
    },
  });
}
