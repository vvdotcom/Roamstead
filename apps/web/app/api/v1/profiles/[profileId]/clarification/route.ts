export const dynamic = "force-dynamic";
export const runtime = "nodejs";
export const maxDuration = 120;

export async function POST(
  request: Request,
  { params }: { params: Promise<{ profileId: string }> },
) {
  const { profileId } = await params;
  const apiUrl = process.env.API_URL ?? "http://127.0.0.1:8000";
  const upstream = await fetch(
    `${apiUrl}/api/v1/profiles/${encodeURIComponent(profileId)}/clarification`,
    {
      method: "POST",
      cache: "no-store",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
        "Accept-Encoding": "identity",
      },
      signal: request.signal,
    },
  );

  return new Response(upstream.body, {
    status: upstream.status,
    headers: {
      "Content-Type": upstream.headers.get("Content-Type") ?? "application/json",
      "Cache-Control": "no-store",
      "Content-Encoding": "identity",
      "X-Accel-Buffering": "no",
    },
  });
}
