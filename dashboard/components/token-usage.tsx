import {
  formatTokenCount,
  tokenCounterRows,
  tokenModelProvenanceLabel,
  tokenUsageSourceLabel,
  tokenUsageStatusLabel,
  type TokenUsage,
  type TokenUsageCounters,
  type TokenUsageSplit,
} from "../lib/token-usage";
import { Icon } from "./icons";

type TokenUsageSectionProps = {
  usage: TokenUsage | null | undefined;
  refreshing: boolean;
};

export function TokenUsageSection({ usage, refreshing }: TokenUsageSectionProps) {
  if (!usage) {
    return (
      <section className="panel token-usage-panel" id="token-usage" aria-label="Consumo de tokens">
        <SectionHeading />
        <div className="token-empty-state" role="status">
          <Icon name="warning-2" size={20} />
          <p>A telemetria de consumo não está disponível nesta versão do serviço.</p>
        </div>
      </section>
    );
  }

  const statusClass = tokenUsageStatusClass(usage.status);

  return (
    <section className="token-usage-panel" id="token-usage" aria-label="Consumo de tokens">
      <div className="token-usage-heading">
        <SectionHeading />
        <span className={`token-status ${statusClass}`} role="status">
          <i /> {refreshing ? "Sincronizando…" : tokenUsageStatusLabel(usage.status)}
        </span>
      </div>

      <div className="token-source-card">
        <div className="token-source-main">
          <span className="token-source-icon"><Icon name="cpu" size={19} /></span>
          <div>
            <strong>{tokenUsageSourceLabel(usage.source.provider)}</strong>
            <p>Formato: {formatSourceFormat(usage.source.format)}</p>
          </div>
        </div>
        <div className="token-sync-time">
          <span>Última sincronização</span>
          <strong>{formatTokenDate(usage.last_synced_at)}</strong>
        </div>
      </div>

      <section className="panel token-inner-panel" aria-label="Cobertura da coleta">
        <div className="panel-header">
          <div><h3>Cobertura da coleta</h3><p>Fontes e observações processadas nesta projeção</p></div>
        </div>
        <div className="token-coverage-grid">
          <CoverageMetric label="Fontes registradas" value={usage.coverage.registered_sources} />
          <CoverageMetric label="Fontes disponíveis" value={usage.coverage.available_sources} />
          <CoverageMetric label="Fontes sincronizadas" value={usage.coverage.synced_sources} />
          <CoverageMetric label="Falhas de sincronização" value={usage.coverage.failed_sources} />
          <CoverageMetric label="Respostas observadas" value={usage.coverage.responses_seen} />
          <CoverageMetric label="Respostas atribuídas" value={usage.coverage.responses_attributed} />
          <CoverageMetric label="Respostas sem atribuição" value={usage.coverage.responses_unassigned} />
          <CoverageMetric label="Modelos identificados" value={usage.coverage.models_known} />
        </div>
      </section>

      <TokenCounterTable
        title="Consumo do orquestrador"
        description="Consumo próprio e total consolidado com os agentes descendentes"
        split={usage.totals}
      />

      <div className="token-usage-grid">
        <section className="panel token-inner-panel">
          <div className="panel-header"><div><h3>Por objetivo</h3><p>Totais próprios e com tarefas descendentes</p></div><span className="panel-count">{usage.goals.length}</span></div>
          {usage.goals.length === 0 ? <TokenEmptyState>Não há objetivos vinculados no período selecionado.</TokenEmptyState> : (
            <div className="table-wrap">
              <table>
                <thead><tr><th>Objetivo</th><th>Estado</th><th>Próprio</th><th>Inclui descendentes</th></tr></thead>
                <tbody>{usage.goals.map((goal) => (
                  <tr key={goal.id}>
                    <td><strong>{goal.name}</strong><small>{goal.id} · {formatTokenDate(goal.started_at)} — {formatTokenDate(goal.ended_at)}</small></td>
                    <td>{displayGoalStatus(goal.status)}</td>
                    <td>{formatTokenCount(goal.own?.total_tokens)}</td>
                    <td>{formatTokenCount(goal.inclusive?.total_tokens)}</td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
          )}
        </section>

        <section className="panel token-inner-panel">
          <div className="panel-header"><div><h3>Por agente</h3><p>Agentes reutilizados permanecem separados por atribuição</p></div><span className="panel-count">{usage.agents.length}</span></div>
          {usage.agents.length === 0 ? <TokenEmptyState>Não há agentes observáveis com consumo atribuído.</TokenEmptyState> : (
            <div className="table-wrap">
              <table>
              <thead><tr><th>Agente</th><th>Objetivo</th><th>Agente pai</th><th>Próprio</th><th>Inclui descendentes</th></tr></thead>
                <tbody>{usage.agents.map((agent) => (
                  <tr key={`${agent.id}:${agent.goal_id ?? "unassigned"}`}>
                    <td><strong>{agent.name}</strong><small>{agent.kind ? displayAgentKind(agent.kind) : agent.id}</small></td>
                    <td>{agent.goal_id ?? "Sem atribuição"}</td>
                    <td>{agent.parent_agent_id ?? "—"}</td>
                    <td>{formatTokenCount(agent.own?.total_tokens)}</td>
                    <td>{formatTokenCount(agent.inclusive?.total_tokens)}</td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
          )}
        </section>
      </div>

      <section className="panel token-inner-panel">
        <div className="panel-header"><div><h3>Por modelo</h3><p>O modelo registrado no contexto do turno não confirma o modelo servido</p></div><span className="panel-count">{usage.models.length}</span></div>
        {usage.models.length === 0 ? <TokenEmptyState>Não há modelos identificados pelas respostas observadas.</TokenEmptyState> : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Modelo</th><th>Proveniência</th><th>Próprio</th><th>Inclui descendentes</th></tr></thead>
              <tbody>{usage.models.map((model) => (
                <tr key={model.id}>
                  <td><strong>{model.name ?? "Modelo não identificado"}</strong><small>{model.provider ?? "Provedor não identificado"}</small></td>
                  <td>{tokenModelProvenanceLabel(model.source, model.verification)}</td>
                  <td>{formatTokenCount(model.own?.total_tokens)}</td>
                  <td>{formatTokenCount(model.inclusive?.total_tokens)}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        )}
      </section>

      <div className="token-detail-grid">
        <section className="panel token-inner-panel unassigned-panel">
          <div className="panel-header"><div><h3>Histórico sem atribuição</h3><p>Uso observado sem vínculo comprovado a objetivo ou agente</p></div></div>
          <div className="unassigned-summary">
            <div><span>Respostas</span><strong>{formatTokenCount(usage.unassigned.response_count)}</strong></div>
            <div><span>Total de tokens informado</span><strong>{formatTokenCount(usage.unassigned.usage?.total_tokens)}</strong></div>
          </div>
        </section>

        <section className="panel token-inner-panel">
          <div className="panel-header"><div><h3>Respostas observadas</h3><p>Metadados de uso; conversas e conteúdo de ferramentas não são exibidos</p></div><span className="panel-count">{usage.responses.length}</span></div>
          {usage.responses.length === 0 ? <TokenEmptyState>Nenhuma resposta de uso está disponível para exibição.</TokenEmptyState> : (
            <div className="table-wrap">
              <table>
                <thead><tr><th>Horário</th><th>Objetivo</th><th>Agente</th><th>Modelo</th><th>Total informado</th><th>Atribuição</th></tr></thead>
                <tbody>{usage.responses.slice(0, 20).map((response) => (
                  <tr key={response.id}>
                    <td>{formatTokenDate(response.recorded_at)}</td>
                    <td>{response.goal_id ?? "Sem atribuição"}</td>
                    <td>{response.agent_name ?? response.agent_id ?? "Não identificado"}</td>
                    <td>{response.model?.name ?? "Desconhecido"}</td>
                    <td>{formatTokenCount(response.usage?.total_tokens)}</td>
                    <td>{displayAttributionStatus(response.attribution_status)}</td>
                  </tr>
                ))}</tbody>
              </table>
              {usage.responses.length > 20 && <p className="table-note">Exibindo 20 das {formatTokenCount(usage.responses.length)} respostas retornadas.</p>}
            </div>
          )}
        </section>
      </div>

      <p className="token-semantics-note">A entrada em cache detalha a entrada e o raciocínio detalha a saída; esses valores não são somados novamente. O total exibido é o informado pela fonte.</p>
    </section>
  );
}

function SectionHeading() {
  return (
    <div className="token-section-heading">
      <span className="token-heading-icon"><Icon name="activity" size={20} /></span>
      <div><span className="section-kicker">TELEMETRIA DE USO</span><h2 id="token-usage-title">Consumo de tokens</h2><p>Uso observado por objetivo, agente e modelo</p></div>
    </div>
  );
}

function TokenCounterTable({ title, description, split }: { title: string; description: string; split: TokenUsageSplit }) {
  return (
    <section className="panel token-inner-panel token-counter-panel">
      <div className="panel-header"><div><h3>{title}</h3><p>{description}</p></div></div>
      <div className="table-wrap">
        <table>
          <thead><tr><th>Contador</th><th>Próprio</th><th>Inclui descendentes</th></tr></thead>
          <tbody>
            <tr><th scope="row">Respostas distintas</th><td>{formatTokenCount(split.own?.response_count)}</td><td>{formatTokenCount(split.inclusive?.response_count)}</td></tr>
            {tokenCounterRows.map((row) => <tr key={row.key}><th scope="row">{row.label}</th><td>{formatTokenCount(readCounter(split.own, row.key))}</td><td>{formatTokenCount(readCounter(split.inclusive, row.key))}</td></tr>)}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function CoverageMetric({ label, value }: { label: string; value: number | null }) {
  return <div className="token-coverage-metric"><span>{label}</span><strong>{formatTokenCount(value)}</strong></div>;
}

function TokenEmptyState({ children }: { children: string }) {
  return <div className="token-empty-state"><Icon name="search-normal" size={17} /><p>{children}</p></div>;
}

function readCounter(counters: TokenUsageCounters | null, key: keyof TokenUsageCounters): number | null {
  return counters?.[key] ?? null;
}

function tokenUsageStatusClass(status: string): string {
  const classes: Record<string, string> = { available: "success", partial: "warning", stale: "warning", incompatible: "danger", unavailable: "neutral" };
  return classes[status] ?? "neutral";
}

function formatSourceFormat(format: string): string {
  if (format === "rollout_jsonl") return "Registros locais do Codex";
  return format || "Formato não informado";
}

function formatTokenDate(value: string | null): string {
  if (!value) return "Não informado";
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return "Não informado";
  return new Intl.DateTimeFormat("pt-BR", { dateStyle: "medium", timeStyle: "short" }).format(date);
}

function displayGoalStatus(status: string): string {
  const labels: Record<string, string> = { active: "Em andamento", completed: "Concluído", failed: "Falhou" };
  return labels[status] ?? "Estado não reconhecido";
}

function displayAgentKind(kind: string): string {
  const labels: Record<string, string> = { orchestrator: "Orquestrador", subagent: "Subagente" };
  return labels[kind] ?? kind;
}

function displayAttributionStatus(status: string): string {
  const labels: Record<string, string> = { attributed: "Atribuída", unassigned: "Sem atribuição", partial: "Parcial" };
  return labels[status] ?? "Estado não reconhecido";
}
