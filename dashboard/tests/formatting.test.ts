import assert from "node:assert/strict";
import test from "node:test";
import { formatExtensionSource, type ExtensionSource } from "../lib/formatting.ts";

test("extension source objects display public provenance without private or raw metadata", () => {
  const source = { repository: "example/helper", target: "helper@example", provider: "github",
                   path: "/private/home/source", ref: "private-ref", commit: "private-commit",
                   token: "synthetic-secret", unexpected: { payload: "never-render-object" } };
  assert.equal(formatExtensionSource(source), "example/helper");
  assert.equal(formatExtensionSource({ target: "helper@example", harness: "codex" }), "helper@example");
  assert.equal(formatExtensionSource({ provider: "github", host: "github.com" }), "github");
  assert.equal(formatExtensionSource({ path: "/private/home/source", ref: "private-ref" }), null);
});

test("extension source labels reject local paths, credential URLs, query strings and oversized values", () => {
  for (const value of ["/private/home/source", "C:\\private\\source", "C:/private/source", "file:///private/source", "https://user:secret@example.invalid/repo",
                       "example/helper?token=synthetic", "example/helper#private", "x".repeat(129), "   "]) {
    assert.equal(formatExtensionSource(value), null, value);
    assert.equal(formatExtensionSource({ repository: value }), null, value);
  }
});

test("malformed source metadata never crashes rendering or serializes nested values", () => {
  for (const source of [{ repository: { token: "synthetic-secret" } }, { target: 7 }, { provider: ["private"] }]) {
    assert.equal(formatExtensionSource(source as unknown as ExtensionSource), null);
  }
  assert.equal(formatExtensionSource(null), null);
  assert.equal(formatExtensionSource(undefined), null);
});

