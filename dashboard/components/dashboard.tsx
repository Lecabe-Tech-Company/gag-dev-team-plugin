"use client";

import { Children, useCallback, useEffect, useMemo, useState, type FormEvent, type ReactNode } from "react";
import { Icon, type IconName } from "./icons";
import { formatExtensionSource, type ExtensionSource } from "../lib/formatting";

type Snapshot = {
  schema_version: number;
  binding?: { project_id?: string; user?: { host?: string; id?: number | string; login?: string } };
  plugin_version?: string;
  revision?: string;
  as_of?: string;
  capabilities?: Record<string, boolean | string | null>;
  environment?: { host?: string; project_id?: string; plugin_version?: string; last_seen_at?: string | null };
  rules: Array<{ id: string; content?: string | null; status: string; content_digest?: string; version?: number; updated_at?: string; source?: string }>;
  skills: Array<{ id: string; name: string; description?: string; status: string; content_digest?: string; version?: number; updated_at?: string; source?: string }>;
  sessions: Array<{ id: string; started_at?: string; ended_at?: string | null; agent_id?: string | null }>;
  issues: Array<{ id: string; status: string; category?: string | null; severity?: string | null; attribution?: string | null; summary: string; opened_at?: string; updated_at?: string; causes?: string[]; attempt_ids?: string[]; model?: ModelInfo | null }>;
  models: Array<ModelInfo & { attempt_count?: number | null; issue_count?: number | null; confirmed_model_issue_count?: number | null }>;
  extensions: Array<{ id: string; extension_id?: string; name?: string; kind?: string; state: string; version?: string; source?: ExtensionSource | null }>;
  diagnostics: string[];
  events: Array<{
    event_id: string;
    event_type: string;
    recorded_at: string;
    issue_id?: string | null;
    category?: string | null;
    severity?: string | null;
    attribution?: string | null;
    summary?: string;
    model?: ModelInfo;
  }>;
  next_cursor?: string | null;
};

type ModelInfo = {
  provider?: string | null;
  requested?: string | null;
  observed?: string | null;
  source?: string;
};

type Health = {
  service: string;
  project_id: string;
  user: { host: string; id: number | string };
  version: string;
  source_hash: string;
};

type FilterValues = {
  period: string;
  from: string;
  to: string;
  model: string;
  category: string;
  status: string;
};

const initialFilters: FilterValues = { period: "30d", from: "", to: "", model: "", category: "", status: "" };
const navigationItems = [
  { id: "overview", label: "Visão geral", icon: "home-2" },
  { id: "personal-context", label: "Regras e skills", icon: "book" },
  { id: "activity", label: "Atividade", icon: "activity" },
  { id: "models", label: "Modelos", icon: "cpu" },
  { id: "extensions", label: "Extensões", icon: "hierarchy-2" },
] as const satisfies Array<{ id: string; label: string; icon: IconName }>;
type DashboardSection = typeof navigationItems[number]["id"];
const statusOptions = [
  "active", "inactive", "open", "resolved", "corrected", "pending", "pending_review", "pending_profile",
  "pending_verification", "pending_host", "pending_auth_or_trust", "pending_auth", "pending_trust", "pending_restart",
  "reviewed", "installed", "failed", "deactivated", "discovered", "downloaded", "requested", "rejected", "stale", "draft", "unknown",
];

export default function Dashboard() {
  const [token, setToken] = useState("");
  const [health, setHealth] = useState<Health | null>(null);
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [filters, setFilters] = useState(initialFilters);
  const [categoryOptions, setCategoryOptions] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [filterError, setFilterError] = useState("");
  const [activeSection, setActiveSection] = useState<DashboardSection>("overview");
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const fragment = new URLSearchParams(window.location.hash.slice(1));
    setToken(fragment.get("access_token") ?? "");
    if (fragment.has("access_token")) {
      window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}`);
    }
    setReady(true);
  }, []);

  useEffect(() => {
    function syncActiveSection() {
      const fragment = window.location.hash.slice(1);
      const matchingItem = navigationItems.find((item) => item.id === fragment);
      setActiveSection(matchingItem?.id ?? "overview");
    }

    syncActiveSection();
    window.addEventListener("hashchange", syncActiveSection);
    return () => window.removeEventListener("hashchange", syncActiveSection);
  }, []);

  const loadSnapshot = useCallback(async (accessToken: string, currentFilters: FilterValues) => {
    setLoading(true);
    setError("");

    try {
      const headers = { Authorization: `Bearer ${accessToken}` };
      const healthResponse = await fetch("/api/health", { headers, cache: "no-store" });
      if (!healthResponse.ok) throw new Error(await getResponseError(healthResponse));

      const verifiedHealth = (await healthResponse.json()) as Health;
      if (verifiedHealth.service !== "gag-personal-environment") {
        throw new Error("A instância local não corresponde ao serviço esperado.");
      }

      const query = new URLSearchParams();
      for (const [name, value] of Object.entries(currentFilters)) {
        if (value) query.set(name, value);
      }
      query.set("limit", "200");

      const querySuffix = query.size > 0 ? `?${query.toString()}` : "";
      const snapshotResponse = await fetch(`/api/snapshot${querySuffix}`, { headers, cache: "no-store" });
      if (!snapshotResponse.ok) throw new Error(await getResponseError(snapshotResponse));

      const data = (await snapshotResponse.json()) as Snapshot;
      if (
        data.binding?.project_id !== verifiedHealth.project_id
        || String(data.binding?.user?.id) !== String(verifiedHealth.user.id)
        || data.binding?.user?.host?.toLowerCase() !== verifiedHealth.user.host.toLowerCase()
        || data.plugin_version !== verifiedHealth.version
      ) {
        throw new Error("Os dados recebidos não correspondem à instância local verificada.");
      }

      setHealth(verifiedHealth);
      setSnapshot(data);
      setCategoryOptions((current) => [...new Set([...current, ...data.events.map((item) => item.category).filter((value): value is string => Boolean(value))])].sort());
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Não foi possível carregar os dados.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (token) void loadSnapshot(token, filters);
  }, [token, loadSnapshot]);

  const activeSessionCount = useMemo(
    () => snapshot?.sessions.filter((session) => !session.ended_at).length ?? 0,
    [snapshot],
  );
  const issueIds = useMemo(() => new Set(snapshot?.issues.map((issue) => issue.id) ?? []), [snapshot]);
  const issueEvents = useMemo(
    () => snapshot?.events.filter((event) => event.event_type.startsWith("issue.") && event.issue_id && issueIds.has(event.issue_id)).slice().reverse() ?? [],
    [snapshot, issueIds],
  );

  function updateFilter(name: keyof FilterValues, value: string) {
    setFilterError("");
    setFilters((current) => ({ ...current, [name]: value }));
  }

  function applyFilters(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (filters.from && filters.to && filters.from > filters.to) {
      setFilterError("A data inicial deve ser anterior ou igual à data final.");
      return;
    }

    setFilterError("");
    if (token) void loadSnapshot(token, toRequestFilters(filters));
  }

  function refresh() {
    if (token) void loadSnapshot(token, toRequestFilters(filters));
  }

  if (!ready) return <main className="loading-shell" aria-label="Carregando painel" />;

  return (
    <main className="dashboard-shell">
      <aside className="sidebar">
        <a className="brand" href="#overview" aria-label="GAG Dev Team — início">
          <span className="brand-mark">G</span>
          <span><strong>GAG Dev Team</strong><small>Ambiente pessoal</small></span>
        </a>
        <nav className="main-nav" aria-label="Navegação principal">
          {navigationItems.map((item) => <a className={`nav-link${activeSection === item.id ? " active" : ""}`} href={`#${item.id}`} aria-label={item.label} aria-current={activeSection === item.id ? "location" : undefined} title={item.label} key={item.id}><Icon name={item.icon} /> <span>{item.label}</span></a>)}
        </nav>
        <div className="sidebar-bottom">
          <span className="local-indicator"><i /> Execução local</span>
          <small>Seus dados permanecem nesta máquina.</small>
        </div>
      </aside>

      <div className="content-area">
        <header className="topbar">
          <div className="breadcrumb"><span>Projeto local</span><b>/</b><strong>Ambiente pessoal</strong></div>
          <div className="topbar-actions">
            <span className="privacy-label"><Icon name="shield-security" size={15} /> Privado neste dispositivo</span>
            <button className="icon-button" type="button" onClick={refresh} disabled={!token || loading} aria-label="Atualizar dados"><Icon name="refresh-circle" size={17} /></button>
            <div className="avatar" aria-label="Conta GitHub">GH</div>
          </div>
        </header>

        <section className="page-content" id="overview">
          <div className="page-heading">
            <div>
              <div className="eyebrow">PAINEL DO AMBIENTE</div>
              <h1>Seu ambiente de trabalho</h1>
              <p>Acompanhe contexto pessoal, atividade dos agentes e extensões instaladas.</p>
            </div>
            <div className="health-pill"><i /> {loading ? "Atualizando" : health ? "Ambiente conectado" : "Aguardando conexão"}</div>
          </div>

          {!token && <div className="notice notice-neutral"><strong>Link de acesso necessário</strong><span>Abra a URL local informada pelo agente para consultar seu ambiente.</span></div>}
          {error && <div className="notice notice-error" role="alert"><strong>Não foi possível carregar o painel</strong><span>{error}</span><button type="button" onClick={refresh}>Tentar novamente</button></div>}
          {!token && <div className="loading-state"><div><strong>Aguardando acesso ao ambiente</strong><p>O painel só exibe dados depois de confirmar o link local seguro.</p></div></div>}

          <section className="environment-card" aria-label="Resumo do ambiente">
            <div className="environment-icon"><Icon name="code-circle" size={24} /></div>
            <div className="environment-copy">
              <span className="section-kicker">AMBIENTE ATUAL</span>
              <h2>{snapshot?.environment?.host ?? "Repositório local"}</h2>
              <p>{snapshot?.environment?.project_id ?? health?.project_id ?? "Aguardando vínculo do projeto"}</p>
            </div>
            <div className="environment-meta">
              <div><span>Conta GitHub</span><strong>{snapshot?.binding?.user?.login ? `@${snapshot.binding.user.login}` : health ? `ID ${health.user.id}` : "—"}</strong></div>
              <div><span>Versão do plugin</span><strong>{snapshot?.plugin_version ?? health?.version ?? "—"}</strong></div>
              <div><span>Última atividade</span><strong>{formatDate(snapshot?.environment?.last_seen_at)}</strong></div>
            </div>
            {health && <span className="verified-label"><i /> Instância verificada</span>}
          </section>

          <form className="filter-panel" onSubmit={applyFilters}>
            <div className="filter-heading"><div><strong className="filter-title"><Icon name="filter" size={17} /> Filtrar atividade</strong><span>Período, modelo e categoria filtram eventos; status também limita listas. O contexto pessoal mostra o estado atual.</span></div><button className="text-button" type="button" onClick={() => { setFilters(initialFilters); setFilterError(""); if (token) void loadSnapshot(token, initialFilters); }}>Limpar filtros</button></div>
            <div className="filter-grid">
              <label>Período<select value={filters.period} onChange={(event) => updateFilter("period", event.target.value)}><option value="24h">Últimas 24 horas</option><option value="7d">Últimos 7 dias</option><option value="30d">Últimos 30 dias</option><option value="all">Todo o histórico</option></select></label>
              <label>De<input type="date" value={filters.from} onChange={(event) => updateFilter("from", event.target.value)} aria-invalid={Boolean(filterError)} aria-describedby={filterError ? "date-filter-error" : undefined} /></label>
              <label>Até<input type="date" value={filters.to} onChange={(event) => updateFilter("to", event.target.value)} aria-invalid={Boolean(filterError)} aria-describedby={filterError ? "date-filter-error" : undefined} /></label>
              <label>Modelo<input value={filters.model} onChange={(event) => updateFilter("model", event.target.value)} placeholder="Qualquer modelo" maxLength={256} /></label>
              <label>Categoria<select value={filters.category} onChange={(event) => updateFilter("category", event.target.value)}><option value="">Todas</option>{categoryOptions.map((category) => <option value={category} key={category}>{displayValue(category)}</option>)}</select></label>
              <label>Status<select value={filters.status} onChange={(event) => updateFilter("status", event.target.value)}><option value="">Todos</option>{statusOptions.map((status) => <option value={status} key={status}>{statusLabel(status)}</option>)}</select></label>
              <button className="button-primary filter-submit" type="submit" disabled={!token || loading}>{loading ? "Carregando…" : "Aplicar filtros"}</button>
            </div>
            {filterError && <p className="filter-error" id="date-filter-error" role="alert">{filterError}</p>}
          </form>

          {loading && !snapshot ? <DashboardSkeleton /> : snapshot ? <>
            <div className="metric-grid" aria-label="Indicadores do ambiente">
              <MetricCard label="Regras pessoais" value={snapshot.rules.length} note="Ativas e históricas" icon="book" tone="violet" />
              <MetricCard label="Skills pessoais" value={snapshot.skills.length} note="Catálogo deste usuário" icon="magic-pen" tone="blue" />
              <MetricCard label="Sessões em andamento" value={activeSessionCount} note={`${snapshot.sessions.length} registradas`} icon="activity" tone="green" />
              <MetricCard label="Eventos de problemas" value={issueEvents.length} note="Até 200 itens da consulta" icon="warning-2" tone="orange" />
            </div>

            <div className="section-grid" id="personal-context">
              <Panel title="Regras do usuário" subtitle="Orientações ativas no contexto pessoal" count={snapshot.rules.length}>
                <RecordList empty="Nenhuma regra registrada para este período.">
                  {snapshot.rules.slice(0, 5).map((rule) => <div className="rule-row" key={`${rule.id}-${rule.version ?? 0}`}><div className="record-title-line"><strong>{rule.id}</strong><StatusBadge status={rule.status} /></div>{rule.content ? <p className="rule-content">{rule.content}</p> : <p className="rule-content muted">Conteúdo indisponível nesta versão do registro.</p>}<span className="record-meta">Versão {rule.version ?? "—"} · {displayValue(rule.source) ?? "Origem não informada"} · {formatDate(rule.updated_at)}</span></div>)}
                </RecordList>
              </Panel>
              <Panel title="Skills do usuário" subtitle="Preferências e fluxos personalizados" count={snapshot.skills.length}>
                <RecordList empty="Nenhuma skill pessoal registrada para este período.">
                  {snapshot.skills.slice(0, 5).map((skill) => <div className="rule-row" key={`${skill.id}-${skill.version ?? 0}`}><div className="record-title-line"><strong>{skill.name}</strong><StatusBadge status={skill.status} /></div><p className="skill-description">{skill.description ?? "Descrição indisponível nesta versão do registro."}</p><span className="record-meta">Versão {skill.version ?? "—"} · {displayValue(skill.source) ?? "Origem não informada"} · {formatDate(skill.updated_at)}</span></div>)}
                </RecordList>
              </Panel>
            </div>

            <div className="section-grid" id="activity">
              <Panel title="Sessões de agentes" subtitle="Execuções identificadas neste projeto" count={snapshot.sessions.length}>
                <RecordList empty="Nenhuma sessão encontrada no período.">
                  {snapshot.sessions.slice(0, 6).map((session) => <RecordRow key={session.id} title={session.agent_id ?? "Agente não identificado"} subtitle={session.id} status={session.ended_at ? "completed" : "running"} date={session.started_at} />)}
                </RecordList>
              </Panel>
              <Panel title="Linha do tempo de problemas" subtitle="Aberturas, resoluções e correções · até 200 eventos" count={issueEvents.length}>
                <RecordList empty="Nenhum evento de problema encontrado nos filtros selecionados.">
                  {issueEvents.slice(0, 8).map((event) => <div className="issue-row" key={event.event_id}>
                    <span className={`severity-mark ${toneForSeverity(event.severity)}`}><Icon name="warning-2" size={14} /></span>
                    <div className="record-main"><div className="record-title-line"><strong>{event.summary || eventTypeLabel(event.event_type)}</strong><StatusBadge status={event.event_type} /></div><span>{[displayValue(event.category), displayValue(event.attribution), event.model ? modelName(event.model) : null].filter(Boolean).join(" · ") || "Sem classificação adicional"}</span></div>
                    <time>{formatDate(event.recorded_at)}</time>
                  </div>)}
                </RecordList>
              </Panel>
            </div>

            <section className="panel model-panel" id="models">
              <div className="panel-header"><div><h2>Métricas por modelo</h2><p>Contagens projetadas a partir dos eventos disponíveis</p></div><span className="panel-count">{snapshot.models.length} modelos</span></div>
              {snapshot.models.length === 0 ? <EmptyState>Não há tentativas instrumentadas neste período.</EmptyState> : <div className="table-wrap"><table><thead><tr><th>Modelo</th><th>Origem do dado</th><th>Tentativas</th><th>Problemas</th><th>Associados ao modelo</th></tr></thead><tbody>{snapshot.models.map((model, index) => <tr key={`${model.provider}-${model.requested}-${model.observed}-${index}`}><td><strong>{modelName(model)}</strong><small>{model.provider ?? "Provedor não identificado"}</small></td><td><StatusBadge status={displayValue(model.source) ?? "desconhecida"} /></td><td>{formatCount(model.attempt_count)}</td><td>{formatCount(model.issue_count)}</td><td>{formatCount(model.confirmed_model_issue_count)}</td></tr>)}</tbody></table></div>}
              <p className="table-note">“Desconhecido” indica ausência de identificação comprovada. Taxas não são exibidas quando não há denominador válido.</p>
            </section>

            <section className="panel extensions-panel" id="extensions">
              <div className="panel-header"><div><h2>Extensões pessoais</h2><p>Plugins e skills disponíveis no perfil local</p></div><span className="panel-count">{snapshot.extensions.length} itens</span></div>
              {snapshot.extensions.length === 0 ? <EmptyState>Nenhuma extensão pessoal registrada.</EmptyState> : <div className="extension-list">{snapshot.extensions.map((extension) => <div className="extension-row" key={extension.id}><span className="extension-icon"><Icon name={extension.kind === "plugin" ? "command" : "magic-pen"} size={17} /></span><div className="record-main"><strong>{extension.name ?? extension.extension_id ?? extension.id}</strong><span>{[displayValue(extension.kind), extension.version, formatExtensionSource(extension.source)].filter(Boolean).join(" · ")}</span></div><StatusBadge status={extension.state} /></div>)}</div>}
            </section>

            {snapshot.diagnostics.length > 0 && <section className="diagnostics-panel"><strong>Observações do ambiente</strong>{snapshot.diagnostics.map((diagnostic, index) => <p key={`${diagnostic}-${index}`}>{diagnostic}</p>)}</section>}
          </> : !error && <DashboardSkeleton />}

          <footer className="page-footer"><span>GAG Dev Team · Painel local</span><span>{snapshot?.as_of ? `Dados atualizados em ${formatDate(snapshot.as_of)}` : "Nenhum dado pessoal é enviado para hospedagem externa."}</span></footer>
        </section>
      </div>
    </main>
  );
}

function MetricCard({ label, value, note, icon, tone }: { label: string; value: number; note: string; icon: IconName; tone: string }) {
  return <article className="metric-card"><span className={`metric-icon ${tone}`}><Icon name={icon} size={18} /></span><span className="metric-label">{label}</span><strong>{value}</strong><small>{note}</small></article>;
}

function Panel({ title, subtitle, count, children }: { title: string; subtitle: string; count: number; children: ReactNode }) {
  return <section className="panel"><div className="panel-header"><div><h2>{title}</h2><p>{subtitle}</p></div><span className="panel-count">{count}</span></div>{children}</section>;
}

function RecordList({ empty, children }: { empty: string; children: ReactNode }) {
  return <div className="record-list">{Children.count(children) > 0 ? children : <EmptyState>{empty}</EmptyState>}</div>;
}

function RecordRow({ title, subtitle, status, date }: { title: string; subtitle: string; status: string; date?: string }) {
  return <div className="record-row"><span className="record-dot" /><div className="record-main"><div className="record-title-line"><strong>{title}</strong><StatusBadge status={status} /></div><span>{subtitle}</span></div><time>{formatDate(date)}</time></div>;
}

function StatusBadge({ status }: { status: string }) {
  const normalized = status.toLowerCase();
  const successStates = new Set(["active", "resolved", "corrected", "completed", "installed", "ativo", "resolvido", "corrigido", "concluída", "instalado"]);
  const warningStates = new Set(["pending", "pending_review", "pending_profile", "pending_verification", "pending_host", "pending_auth", "pending_trust", "pending_auth_or_trust", "pending_restart", "stale", "draft", "discovered", "requested", "running", "pendente", "desconhecido"]);
  const dangerStates = new Set(["failed", "rejected", "tampered", "erro", "error", "blocked", "recusado", "falhou"]);
  const tone = successStates.has(normalized) ? "success" : warningStates.has(normalized) ? "warning" : dangerStates.has(normalized) ? "danger" : "neutral";

  return <span className={`status-badge ${tone}`}>{statusLabel(status)}</span>;
}

function EmptyState({ children }: { children: ReactNode }) {
  return <div className="empty-state"><Icon name="search-normal" size={18} /><p>{children}</p></div>;
}

function DashboardSkeleton() {
  return <div className="loading-state" aria-live="polite"><span className="spinner" /><div><strong>Carregando seu ambiente</strong><p>Consultando os dados locais vinculados à sua conta.</p></div></div>;
}

function formatDate(value?: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return "—";
  return new Intl.DateTimeFormat("pt-BR", { dateStyle: "medium", timeStyle: "short" }).format(date);
}

function formatCount(value?: number | null): string {
  return Number.isFinite(value) ? new Intl.NumberFormat("pt-BR").format(value ?? 0) : "—";
}

function modelName(model?: ModelInfo | null): string {
  if (!model) return "Modelo não identificado";
  return model.observed ?? model.requested ?? "Modelo desconhecido";
}

function statusLabel(status: string): string {
  const knownLabels: Record<string, string> = {
    active: "Ativa", inactive: "Inativa", enabled: "Habilitada", disabled: "Desativada",
    open: "Aberto", resolved: "Resolvido", corrected: "Corrigido", pending: "Pendente",
    installed: "Instalada", downloaded: "Baixada", failed: "Falhou", running: "Em andamento",
    completed: "Concluída", unknown: "Desconhecido", observed: "Observado", declared: "Declarado",
    configured: "Configurado", reviewed: "Revisada", deactivated: "Desativada",
    discovered: "Descoberta", requested: "Solicitada", rejected: "Recusada", pending_host: "Aguardando cliente",
    "pending_auth": "Aguardando autenticação", "pending_trust": "Aguardando confiança", "pending_auth_or_trust": "Aguardando autenticação ou confiança",
    "pending_restart": "Aguardando reinício", "pending_authorization": "Aguardando autorização",
    "pending_profile": "Aguardando perfil", "pending_verification": "Aguardando verificação", "pending_review": "Aguardando revisão",
    stale: "Revisão desatualizada", tampered: "Integridade comprometida", draft: "Rascunho",
    "issue.opened": "Aberto", "issue.resolved": "Resolvido", "issue.corrected": "Corrigido",
    "in progress": "Em andamento",
  };
  return knownLabels[status.toLowerCase()] ?? status;
}

function eventTypeLabel(eventType: string): string {
  const labels: Record<string, string> = {
    "issue.opened": "Problema aberto", "issue.resolved": "Problema resolvido",
    "issue.corrected": "Problema corrigido",
  };
  return labels[eventType] ?? "Evento de problema";
}

function displayValue(value?: string | null): string | null {
  if (!value) return null;
  const knownValues: Record<string, string> = {
    agent: "Agente", tool: "Ferramenta", environment: "Ambiente", clarification: "Esclarecimento",
    implementation: "Implementação", observed: "Observado", configured: "Configurado",
    declared: "Declarado", unknown: "Desconhecido", plugin: "Plugin", skill: "Skill",
  };
  return knownValues[value.toLowerCase()] ?? value;
}

function toRequestFilters(values: FilterValues): FilterValues {
  return {
    ...values,
    from: values.from ? localDateBoundary(values.from, false) : "",
    to: values.to ? localDateBoundary(values.to, true) : "",
  };
}

function localDateBoundary(value: string, endOfDay: boolean): string {
  const [year, month, day] = value.split("-").map(Number);
  const date = endOfDay
    ? new Date(year, month - 1, day, 23, 59, 59, 999)
    : new Date(year, month - 1, day, 0, 0, 0, 0);
  return date.toISOString();
}

function toneForSeverity(severity?: string | null): string {
  if (!severity) return "severity-neutral";
  if (/critical|high|alta|crítica/i.test(severity)) return "severity-high";
  if (/medium|média/i.test(severity)) return "severity-medium";
  return "severity-low";
}

async function getResponseError(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as { error?: string };
    return payload.error ?? "A solicitação não foi autorizada.";
  } catch {
    return "A solicitação não foi autorizada.";
  }
}
