export type TokenUsageStatus = "available" | "partial" | "stale" | "incompatible" | "unavailable";

export type TokenUsageCounters = {
  response_count: number | null;
  input_tokens: number | null;
  cached_input_tokens: number | null;
  cache_write_input_tokens: number | null;
  output_tokens: number | null;
  reasoning_output_tokens: number | null;
  total_tokens: number | null;
};

export type TokenUsageSplit = {
  own: TokenUsageCounters | null;
  inclusive: TokenUsageCounters | null;
};

export type TokenUsageGoal = TokenUsageSplit & {
  id: string;
  name: string;
  status: string;
  started_at: string | null;
  ended_at: string | null;
};

export type TokenUsageAgent = TokenUsageSplit & {
  id: string;
  name: string;
  parent_agent_id: string | null;
  goal_id: string | null;
  kind: string | null;
};

export type TokenUsageModel = TokenUsageSplit & {
  id: string;
  name: string | null;
  provider: string | null;
  source: string;
  verification: string;
};

export type TokenUsageResponse = {
  id: string;
  recorded_at: string;
  goal_id: string | null;
  agent_id: string | null;
  agent_name: string | null;
  model: TokenUsageModelIdentity | null;
  usage: TokenUsageCounters | null;
  attribution_status: string;
};

export type TokenUsageModelIdentity = {
  name: string | null;
  provider: string | null;
  source: string | null;
  verification: string | null;
};

export type TokenUsageCoverage = {
  registered_sources: number | null;
  available_sources: number | null;
  synced_sources: number | null;
  failed_sources: number | null;
  responses_seen: number | null;
  responses_attributed: number | null;
  responses_unassigned: number | null;
  models_known: number | null;
};

export type TokenUsage = {
  source: { provider: string; format: string; status: TokenUsageStatus };
  status: TokenUsageStatus;
  last_synced_at: string | null;
  coverage: TokenUsageCoverage;
  totals: TokenUsageSplit;
  goals: TokenUsageGoal[];
  agents: TokenUsageAgent[];
  models: TokenUsageModel[];
  unassigned: { response_count: number | null; usage: TokenUsageCounters | null };
  responses: TokenUsageResponse[];
};

export const tokenCounterRows = [
  { key: "input_tokens", label: "Entrada" },
  { key: "cached_input_tokens", label: "Entrada em cache (detalhe)" },
  { key: "cache_write_input_tokens", label: "Escrita em cache" },
  { key: "output_tokens", label: "Saída" },
  { key: "reasoning_output_tokens", label: "Raciocínio (detalhe da saída)" },
  { key: "total_tokens", label: "Total informado pela fonte" },
] as const satisfies Array<{ key: keyof TokenUsageCounters; label: string }>;

export function formatTokenCount(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "Não informado";
  return new Intl.NumberFormat("pt-BR").format(value);
}

export function tokenUsageStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    available: "Disponível",
    partial: "Cobertura parcial",
    stale: "Dados desatualizados",
    incompatible: "Formato incompatível",
    unavailable: "Coleta indisponível",
  };
  return labels[status] ?? "Estado não reconhecido";
}

export function tokenUsageSourceLabel(provider: string): string {
  if (provider.toLowerCase() === "codex") return "Codex";
  return provider || "Origem não informada";
}

export function tokenModelProvenanceLabel(source: string, verification: string): string {
  if (source === "turn_context" && verification === "requested") return "Modelo solicitado pelo host";
  if (verification === "observed") return "Modelo observado";
  return "Proveniência não confirmada";
}
