export type ExtensionSource = string | {
  provider?: string;
  host?: string;
  repository?: string;
  path?: string;
  ref?: string;
  commit?: string;
  target?: string;
  harness?: string;
};

export function formatExtensionSource(source?: ExtensionSource | null): string | null {
  if (!source) return null;
  if (typeof source === "string") return safeSourceLabel(source);

  const label = source.repository ?? source.target ?? source.provider ?? source.host ?? source.harness;
  return label ? safeSourceLabel(label) : null;
}

function safeSourceLabel(value: string): string | null {
  if (typeof value !== "string") return null;
  const normalized = value.trim();
  if (
    !normalized
    || normalized.length > 128
    || normalized.startsWith("/")
    || /^[a-z]:\//i.test(normalized)
    || normalized.includes("\\")
    || /^file:/i.test(normalized)
    || normalized.includes("?")
    || normalized.includes("#")
    || /:\/\/[^/]*@/.test(normalized)
  ) {
    return null;
  }

  return normalized;
}
