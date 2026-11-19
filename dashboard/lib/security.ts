import { timingSafeEqual } from "node:crypto";

export type SnapshotFilters = Record<string, string>;

const allowedFilterNames = new Set([
  "period",
  "from",
  "to",
  "model",
  "category",
  "status",
  "cursor",
  "limit",
]);

const allowedPeriods = new Set(["all", "24h", "7d", "30d"]);

export class RequestValidationError extends Error {
  readonly statusCode: number;

  constructor(message: string, statusCode = 400) {
    super(message);
    this.name = "RequestValidationError";
    this.statusCode = statusCode;
  }
}

export function parseSnapshotFilters(queryParameters: URLSearchParams): SnapshotFilters {
  const filters: SnapshotFilters = {};

  for (const [name, value] of queryParameters.entries()) {
    if (!allowedFilterNames.has(name)) {
      throw new RequestValidationError("Filtro não permitido.");
    }

    if (filters[name] !== undefined) {
      throw new RequestValidationError("Filtro repetido.");
    }

    if (value.length > 256 || value.trim().length === 0) {
      throw new RequestValidationError("Valor de filtro inválido.");
    }

    filters[name] = value;
  }

  if (filters.period !== undefined && !allowedPeriods.has(filters.period)) {
    throw new RequestValidationError("Período inválido.");
  }

  for (const name of ["from", "to"]) {
    const value = filters[name];
    if (value !== undefined && !isIsoDate(value)) {
      throw new RequestValidationError("Data inválida.");
    }
  }

  if (filters.from && filters.to && Date.parse(filters.from) > Date.parse(filters.to)) {
    throw new RequestValidationError("Intervalo de datas inválido.");
  }

  if (filters.limit !== undefined) {
    if (!/^\d+$/.test(filters.limit)) {
      throw new RequestValidationError("Limite inválido.");
    }

    const limit = Number(filters.limit);
    if (!Number.isSafeInteger(limit) || limit < 1 || limit > 200) {
      throw new RequestValidationError("Limite fora do intervalo permitido.");
    }
  }

  return filters;
}

export function isAuthorizedLocalRequest(
  request: Request,
  expectedHost: string | undefined,
  expectedToken: string | undefined,
): boolean {
  if (!expectedHost || !expectedToken || !isLoopbackHost(expectedHost)) {
    return false;
  }

  const hostHeader = request.headers.get("host");
  if (!hostHeader || normalizeHost(hostHeader) !== normalizeHost(expectedHost)) {
    return false;
  }

  const originHeader = request.headers.get("origin");
  if (originHeader !== null) {
    let origin: URL;
    try {
      origin = new URL(originHeader);
    } catch {
      return false;
    }

    if (origin.protocol !== "http:" || normalizeHost(origin.host) !== normalizeHost(expectedHost)) {
      return false;
    }
  }

  const authorization = request.headers.get("authorization");
  if (!authorization?.startsWith("Bearer ")) {
    return false;
  }

  const presentedToken = authorization.slice("Bearer ".length);
  const expectedBytes = Buffer.from(expectedToken, "utf8");
  const presentedBytes = Buffer.from(presentedToken, "utf8");

  return expectedBytes.length === presentedBytes.length && timingSafeEqual(expectedBytes, presentedBytes);
}

export function readDashboardConfig(environment: Record<string, string | undefined> = process.env) {
  const rawBinding = environment.GAG_DASHBOARD_BINDING;
  const expectedToken = environment.GAG_DASHBOARD_TOKEN;
  const expectedHost = environment.GAG_DASHBOARD_ALLOWED_HOST;

  if (!rawBinding || !expectedToken || !expectedHost || !isLoopbackHost(expectedHost)) {
    throw new Error("Dashboard configuration is incomplete.");
  }

  let binding: unknown;
  try {
    binding = JSON.parse(rawBinding);
  } catch {
    throw new Error("Dashboard binding is invalid.");
  }

  if (!isRecord(binding)) {
    throw new Error("Dashboard binding is invalid.");
  }

  return { binding, expectedHost, expectedToken };
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function isLoopbackHost(host: string): boolean {
  const normalizedHost = normalizeHost(host);
  const localHostMatch = /^(?:127\.0\.0\.1|localhost)(?::(\d+))?$/.exec(normalizedHost);
  const localAddressMatch = /^\[::1\](?::(\d+))?$/.exec(normalizedHost);
  const portText = localHostMatch?.[1] ?? localAddressMatch?.[1];

  if (!localHostMatch && !localAddressMatch) return false;
  if (portText === undefined) return true;

  const port = Number(portText);
  return Number.isInteger(port) && port >= 1 && port <= 65535;
}

function isIsoDate(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,9})?)?(?:Z|[+-]\d{2}:\d{2})?)?$/.test(value)) {
    return false;
  }

  const datePart = value.slice(0, 10);
  const parsedDate = new Date(`${datePart}T00:00:00.000Z`);
  return Number.isFinite(Date.parse(value)) && parsedDate.toISOString().slice(0, 10) === datePart;
}

function normalizeHost(host: string): string {
  return host.trim().toLowerCase().replace(/\.$/, "");
}
