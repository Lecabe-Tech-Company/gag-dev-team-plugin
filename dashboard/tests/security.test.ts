import assert from "node:assert/strict";
import { test } from "node:test";
import {
  isAuthorizedLocalRequest,
  isLoopbackHost,
  parseSnapshotFilters,
  readDashboardConfig,
  RequestValidationError,
} from "../lib/security.ts";

const host = "127.0.0.1:4567";
const token = "synthetic-local-dashboard-capability";

function request(headers: Record<string, string> = {}): Request {
  return new Request(`http://${host}/api/snapshot`, {
    headers: { host, authorization: `Bearer ${token}`, ...headers },
  });
}

test("protected reads require matching loopback host, origin and bearer token", () => {
  assert.equal(isAuthorizedLocalRequest(request(), host, token), true);
  assert.equal(isAuthorizedLocalRequest(request({ origin: `http://${host}` }), host, token), true);
  const deniedHeaders: Array<Record<string, string>> = [
    { host: "attacker.example:4567" },
    { host: "127.0.0.1:9999" },
    { origin: "https://attacker.example" },
    { origin: "null" },
    { origin: "http://127.0.0.1:9999" },
    { authorization: "" },
    { authorization: "Bearer another-token" },
    { authorization: "Basic synthetic" },
  ];
  for (const headers of deniedHeaders) {
    assert.equal(isAuthorizedLocalRequest(request(headers), host, token), false);
  }
  assert.equal(isAuthorizedLocalRequest(request(), undefined, token), false);
  assert.equal(isAuthorizedLocalRequest(request(), host, undefined), false);
});

test("loopback validation rejects external, wildcard and malformed hosts", () => {
  assert.equal(isLoopbackHost(host), true);
  assert.equal(isLoopbackHost("localhost:4567"), true);
  for (const candidate of [
    "0.0.0.0:4567", "attacker.example:4567", "127.0.0.1.attacker.example:4567",
    "localhost.attacker.example:4567", "127.0.0.1:4567@attacker.example", "127.0.0.1:not-a-port",
  ]) {
    assert.equal(isLoopbackHost(candidate), false, candidate);
  }
});

test("supported filters preserve caller values without accepting paths or other identities", () => {
  const filters = new URLSearchParams({
    period: "7d", from: "2026-11-01T00:00:00Z", to: "2026-11-18T23:59:59Z",
    model: "synthetic-observed-model", category: "environment", status: "open", limit: "200",
    goal_id: "goal-alpha", agent_id: "agent-root",
  });
  assert.deepEqual(parseSnapshotFilters(filters), Object.fromEntries(filters));
  assert.deepEqual(parseSnapshotFilters(new URLSearchParams()), {});
  for (const name of ["path", "user_id", "project_id", "private_root"]) {
    assert.throws(() => parseSnapshotFilters(new URLSearchParams({ [name]: "synthetic" })), RequestValidationError);
  }
});

test("invalid filter periods, duplicate values, lengths and limits are rejected", () => {
  for (const query of [
    "period=year", "limit=0", "limit=201", "limit=-1", "limit=1.5", "limit=Infinity",
    "model=", "model=first&model=second", `model=${"x".repeat(257)}`,
    "from=not-a-date", "from=2026-02-30", "from=2026-11-19&to=2026-11-18",
  ]) {
    assert.throws(() => parseSnapshotFilters(new URLSearchParams(query)), RequestValidationError, query);
  }
  assert.deepEqual(parseSnapshotFilters(new URLSearchParams("limit=1")), { limit: "1" });
});

test("configuration requires private binding and local access credentials", () => {
  const environment = {
    GAG_DASHBOARD_BINDING: JSON.stringify({ project_id: "synthetic-project", user: { id: 101 } }),
    GAG_DASHBOARD_TOKEN: token,
    GAG_DASHBOARD_ALLOWED_HOST: host,
  };
  const configured = readDashboardConfig(environment);
  assert.equal(configured.expectedToken, token);
  assert.equal(configured.expectedHost, host);
  for (const changes of [
    { GAG_DASHBOARD_BINDING: "{" }, { GAG_DASHBOARD_BINDING: "[]" },
    { GAG_DASHBOARD_TOKEN: "" }, { GAG_DASHBOARD_ALLOWED_HOST: "attacker.example:4567" },
  ]) {
    assert.throws(() => readDashboardConfig({ ...environment, ...changes }));
  }
});
