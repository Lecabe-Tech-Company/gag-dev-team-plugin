import { NextResponse } from "next/server";
import { isAuthorizedLocalRequest, isRecord, readDashboardConfig } from "@/lib/security";

export const dynamic = "force-dynamic";

export function GET(request: Request) {
  let configuration;
  try {
    configuration = readDashboardConfig();
  } catch {
    return jsonResponse({ error: "Dashboard indisponível." }, 503);
  }

  if (!isAuthorizedLocalRequest(request, configuration.expectedHost, configuration.expectedToken)) {
    return jsonResponse({ error: "Acesso não autorizado." }, 401);
  }

  const { binding } = configuration;
  const user = binding.user;
  if (!isRecord(user) || typeof binding.project_id !== "string" || typeof user.host !== "string" || user.id === undefined) {
    return jsonResponse({ error: "Vínculo do ambiente inválido." }, 503);
  }

  return jsonResponse({
    service: "gag-personal-environment",
    project_id: binding.project_id,
    user: { host: user.host, id: user.id },
    version: process.env.GAG_DASHBOARD_VERSION ?? "unknown",
    source_hash: process.env.GAG_DASHBOARD_SOURCE_HASH ?? "unknown",
  });
}

function jsonResponse(body: Record<string, unknown>, status = 200) {
  return NextResponse.json(body, {
    status,
    headers: { "Cache-Control": "private, no-store, max-age=0" },
  });
}
