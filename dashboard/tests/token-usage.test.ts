import assert from "node:assert/strict";
import test from "node:test";
import { formatTokenCount, tokenUsageStatusLabel, tokenModelProvenanceLabel } from "../lib/token-usage.ts";

test("token display distinguishes missing measurements from explicit zero and preserves source counts", () => {
  assert.equal(formatTokenCount(null), "Não informado");
  assert.equal(formatTokenCount(undefined), "Não informado");
  assert.equal(formatTokenCount(Number.NaN), "Não informado");
  assert.equal(formatTokenCount(Number.POSITIVE_INFINITY), "Não informado");
  assert.equal(formatTokenCount(0), "0");
  assert.equal(formatTokenCount(120), "120");
  assert.equal(formatTokenCount(1234567), "1.234.567");
});

test("partial stale incompatible and unavailable collection have distinct honest states", () => {
  const labels = ["available", "partial", "stale", "incompatible", "unavailable"].map(tokenUsageStatusLabel);
  assert.equal(new Set(labels).size, 5);
  assert.match(tokenUsageStatusLabel("partial"), /parcial/i);
  assert.match(tokenUsageStatusLabel("stale"), /desatualizad/i);
  assert.match(tokenUsageStatusLabel("incompatible"), /incompatível/i);
  assert.match(tokenUsageStatusLabel("unavailable"), /indisponível/i);
  assert.notEqual(tokenUsageStatusLabel("future-format"), tokenUsageStatusLabel("available"));
});

test("host requested model metadata is never labeled as provider served confirmation", () => {
  const requested = tokenModelProvenanceLabel("turn_context", "requested");
  assert.match(requested, /solicitado/i);
  assert.doesNotMatch(requested, /servido|efetivamente|confirmado pelo provedor/i);
  const unknown = tokenModelProvenanceLabel("unknown", "unknown");
  assert.match(unknown, /não confirmada/i);
  assert.notEqual(requested, tokenModelProvenanceLabel("provider", "observed"));
});

