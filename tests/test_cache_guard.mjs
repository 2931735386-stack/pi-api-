import assert from "node:assert/strict";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { pathToFileURL } from "node:url";

const temp = await mkdtemp(join(tmpdir(), "pi-cache-guard-test-"));
process.env.PI_CODING_AGENT_DIR = temp;
const configPath = join(temp, "cache-compat-guard.json");
const piRoot = join(
  process.env.APPDATA,
  "npm",
  "node_modules",
  "@earendil-works",
  "pi-coding-agent",
);
const { createJiti } = await import(pathToFileURL(join(
  piRoot,
  "node_modules",
  "jiti",
  "lib",
  "jiti-static.mjs",
)).href);
const jiti = createJiti(import.meta.url, {
  alias: {
    "@earendil-works/pi-coding-agent": join(piRoot, "dist", "index.js"),
  },
});

async function setConfig(providers = {}, models = {}, defaultPolicy = "auto") {
  await writeFile(configPath, JSON.stringify({
    version: 1,
    defaultPolicy,
    providers,
    models,
    nonce: Math.random().toString(36),
  }), "utf8");
}

try {
  await setConfig();
  const module = await jiti.import(join(
    process.cwd(),
    "cache-compat-guard",
    "index.ts",
  ));
  const internals = module.__internals_for_tests;
  assert.ok(internals, "test internals should be exported through Jiti");

  const sessionId = "01-test-raw-session-id";
  const ctx = { sessionManager: { getSessionId: () => sessionId } };
  const proxy = {
    provider: "proxy",
    id: "deepseek-v4-flash",
    api: "openai-completions",
    baseUrl: "https://proxy.example/v1",
  };

  const safePayload = {
    model: proxy.id,
    prompt_cache_key: sessionId,
    prompt_cache_retention: "24h",
  };
  const safeChanges = internals.applyPayloadPolicy(safePayload, proxy, ctx);
  assert.equal("prompt_cache_key" in safePayload, false);
  assert.equal("prompt_cache_retention" in safePayload, false);
  assert.ok(safeChanges.includes("prompt_cache_key"));
  assert.ok(safeChanges.includes("prompt_cache_retention"));

  await setConfig({ proxy: "key" });
  const keyPayload = {
    model: proxy.id,
    prompt_cache_key: sessionId,
    prompt_cache_retention: "24h",
  };
  internals.applyPayloadPolicy(keyPayload, proxy, ctx);
  assert.match(keyPayload.prompt_cache_key, /^[a-f0-9]{32}$/);
  assert.notEqual(keyPayload.prompt_cache_key, sessionId);
  assert.equal("prompt_cache_retention" in keyPayload, false);

  await setConfig({ proxy: "long" });
  const longPayload = {
    model: proxy.id,
    prompt_cache_key: sessionId,
    prompt_cache_retention: "24h",
  };
  internals.applyPayloadPolicy(longPayload, proxy, ctx);
  assert.match(longPayload.prompt_cache_key, /^[a-f0-9]{32}$/);
  assert.equal(longPayload.prompt_cache_retention, "24h");

  await setConfig({ proxy: "strict" });
  const headers = {
    Session_ID: sessionId,
    "X-Client-Request-Id": sessionId,
    Authorization: "secret-placeholder",
  };
  assert.equal(internals.deleteCaseInsensitiveHeader(headers, "session_id"), true);
  assert.equal(internals.deleteCaseInsensitiveHeader(headers, "x-client-request-id"), true);
  assert.equal(headers.Session_ID, null);
  assert.equal(headers["X-Client-Request-Id"], null);
  assert.equal(headers.Authorization, "secret-placeholder");

  const official = {
    provider: "openai",
    id: "gpt-test",
    api: "openai-completions",
    baseUrl: "https://api.openai.com/v1",
  };
  await setConfig();
  const officialPayload = {
    model: official.id,
    prompt_cache_key: sessionId,
    prompt_cache_retention: "24h",
  };
  internals.applyPayloadPolicy(officialPayload, official, ctx);
  assert.equal(officialPayload.prompt_cache_key, sessionId);
  assert.equal(officialPayload.prompt_cache_retention, "24h");

  assert.equal(
    internals.isOfficialOpenAIBaseUrl("https://api.openai.com.evil.example/v1"),
    false,
  );
  console.log("cache guard runtime tests: OK");
} finally {
  await rm(temp, { recursive: true, force: true });
}
