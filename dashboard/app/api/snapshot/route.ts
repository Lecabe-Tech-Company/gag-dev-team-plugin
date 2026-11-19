import { NextResponse } from "next/server";
import { readSnapshot } from "@/lib/snapshot";
import { isAuthorizedLocalRequest, parseSnapshotFilters, readDashboardConfig, RequestValidationError } from "@/lib/security";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET(request: Request) {
  let configuration;
  try {
    configuration = readDashboardConfig();
  } catch {
    return jsonResponse({ error: "Dashboard indisponível." }, 503);
  }

  if (!isAuthorizedLocalRequest(request, configuration.expectedHost, configuration.expectedToken)) {
    return jsonResponse({ error: "Acesso não autorizado." }, 401);
  }

  let filters;
  try {
    filters = parseSnapshotFilters(new URLSearchParams(new URL(request.url).search));
  } catch (error) {
    if (error instanceof RequestValidationError) {
      return jsonResponse({ error: error.message }, error.statusCode);
    }
    return jsonResponse({ error: "Filtros inválidos." }, 400);
  }

  try {
    const snapshot = await readSnapshot(configuration.binding, filters);
    return jsonResponse(snapshot);
  } catch {
    return jsonResponse({ error: "Não foi possível carregar o ambiente agora." }, 503);
  }
}

function jsonResponse(body: Record<string, unknown>, status = 200) {
  return NextResponse.json(body, {
    status,
    headers: { "Cache-Control": "private, no-store, max-age=0" },
  });
}
