// Managed by pi-api-switcher. Remove this line to prevent automatic updates.
import { createHash } from "node:crypto";
import { readFileSync, statSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";

type UnknownRecord = Record<string, unknown>;
type CachePolicy = "auto" | "strict" | "key" | "long";
type EffectiveCachePolicy = "safe" | "strict" | "key" | "long";

type GuardConfig = {
	version?: number;
	defaultPolicy?: CachePolicy;
	providers?: Record<string, CachePolicy>;
	models?: Record<string, CachePolicy>;
};

type CachedConfig = {
	signature: string;
	value: GuardConfig;
};

const AGENT_DIR = process.env.PI_CODING_AGENT_DIR || join(homedir(), ".pi", "agent");
const CONFIG_PATH = join(AGENT_DIR, "cache-compat-guard.json");
const OFFICIAL_OPENAI_HOSTS = new Set(["api.openai.com"]);
const DEBUG_ENV = "PI_CACHE_COMPAT_GUARD_DEBUG";
const AFFINITY_HEADERS = [
	"session_id",
	"x-client-request-id",
	"x-session-affinity",
	"x-session-id",
];

let cachedConfig: CachedConfig | undefined;
let lastModelKey = "";
let lastPolicy: CachePolicy | undefined;
let lastRemoved: string[] = [];

function asRecord(value: unknown): UnknownRecord | undefined {
	return typeof value === "object" && value !== null && !Array.isArray(value)
		? value as UnknownRecord
		: undefined;
}

function isEnabledEnv(value: string | undefined): boolean {
	return ["1", "true", "yes", "on"].includes(value?.trim().toLowerCase() ?? "");
}

function normalizePolicy(value: unknown): CachePolicy | undefined {
	return value === "auto" || value === "strict" || value === "key" || value === "long"
		? value
		: undefined;
}

function configSignature(): string {
	try {
		const info = statSync(CONFIG_PATH);
		return `${info.size}:${info.mtimeMs}:${info.ctimeMs}`;
	} catch {
		return "missing";
	}
}

function readConfig(): GuardConfig {
	const signature = configSignature();
	if (cachedConfig?.signature === signature) return cachedConfig.value;

	let value: GuardConfig = { version: 1, defaultPolicy: "auto", providers: {}, models: {} };
	if (signature !== "missing") {
		try {
			const parsed = asRecord(JSON.parse(readFileSync(CONFIG_PATH, "utf8")));
			const providerInput = asRecord(parsed?.providers);
			const modelInput = asRecord(parsed?.models);
			const providers: Record<string, CachePolicy> = {};
			const models: Record<string, CachePolicy> = {};
			for (const [key, raw] of Object.entries(providerInput ?? {})) {
				const policy = normalizePolicy(raw);
				if (policy) providers[key] = policy;
			}
			for (const [key, raw] of Object.entries(modelInput ?? {})) {
				const policy = normalizePolicy(raw);
				if (policy) models[key] = policy;
			}
			value = {
				version: 1,
				defaultPolicy: normalizePolicy(parsed?.defaultPolicy) ?? "auto",
				providers,
				models,
			};
		} catch {
			// Malformed or unreadable config must fail closed via the safe auto policy.
		}
	}
	cachedConfig = { signature, value };
	return value;
}

function isOpenAICompatibleApi(api: unknown): boolean {
	return api === "openai-completions" || api === "openai-responses" || api === "azure-openai-responses";
}

function isOfficialOpenAIBaseUrl(baseUrl: unknown): boolean {
	if (typeof baseUrl !== "string" || !baseUrl.trim()) return false;
	try {
		return OFFICIAL_OPENAI_HOSTS.has(new URL(baseUrl).hostname.toLowerCase());
	} catch {
		return false;
	}
}

function isPiBuiltInLlamaCppModel(model: NonNullable<ExtensionContext["model"]>): boolean {
	if (model.provider !== "llama.cpp" || model.api !== "openai-completions") return false;
	const compat = asRecord(model.compat);
	return compat?.supportsStore === false
		&& compat?.supportsDeveloperRole === false
		&& compat?.supportsReasoningEffort === false
		&& compat?.supportsUsageInStreaming === false
		&& compat?.supportsStrictMode === false
		&& compat?.maxTokensField === "max_tokens"
		&& compat?.supportsLongCacheRetention === undefined;
}

function configuredPolicy(model: NonNullable<ExtensionContext["model"]>): CachePolicy {
	const config = readConfig();
	const key = `${model.provider}/${model.id}`;
	return config.models?.[key]
		?? config.providers?.[model.provider]
		?? config.defaultPolicy
		?? "auto";
}

function effectivePolicy(model: NonNullable<ExtensionContext["model"]>): EffectiveCachePolicy {
	const policy = configuredPolicy(model);
	if (policy !== "auto") return policy;
	// Pi's built-in llama.cpp transport uses a session cache key without long
	// retention. Unknown third-party endpoints otherwise fail closed.
	if (isPiBuiltInLlamaCppModel(model)) return "key";
	return isOfficialOpenAIBaseUrl(model.baseUrl) ? "long" : "safe";
}

function deleteCaseInsensitiveHeader(
	headers: Record<string, string | null | undefined>,
	name: string,
): boolean {
	let changed = false;
	for (const current of Object.keys(headers)) {
		if (current.toLowerCase() === name.toLowerCase()) {
			headers[current] = null;
			changed = true;
		}
	}
	return changed;
}

function opaqueSessionKey(ctx: ExtensionContext, modelKey: string): string | undefined {
	const sessionId = ctx.sessionManager.getSessionId();
	if (!sessionId) return undefined;
	return createHash("sha256")
		.update("pi-api-switcher-cache-v1\0")
		.update(modelKey)
		.update("\0")
		.update(sessionId)
		.digest("hex")
		.slice(0, 32);
}

function deletePayloadField(payload: UnknownRecord, key: string): boolean {
	const hadWireValue = Object.prototype.hasOwnProperty.call(payload, key)
		&& payload[key] !== undefined;
	delete payload[key];
	return hadWireValue;
}

function ensurePromptCacheKey(
	payload: UnknownRecord,
	key: string | undefined,
	rawSessionId?: string,
): boolean {
	if (!key) return false;
	const snakeKey = typeof payload.prompt_cache_key === "string" ? payload.prompt_cache_key.trim() : "";
	const camelKey = typeof payload.promptCacheKey === "string" ? payload.promptCacheKey.trim() : "";
	// Preserve an explicit custom key, but replace Pi's raw session id with an
	// opaque provider/model-scoped digest before it is sent through a proxy.
	if (snakeKey && snakeKey !== rawSessionId) return false;
	if (!snakeKey && camelKey && camelKey !== rawSessionId) return false;
	payload.prompt_cache_key = key;
	delete payload.promptCacheKey;
	return snakeKey !== key || !!camelKey;
}

function applyPayloadPolicy(
	payloadValue: unknown,
	model: NonNullable<ExtensionContext["model"]>,
	ctx: ExtensionContext,
): string[] {
	const payload = asRecord(payloadValue);
	if (!payload || !isOpenAICompatibleApi(model.api)) return [];

	const policy = effectivePolicy(model);
	const modelKey = `${model.provider}/${model.id}`;
	const changed: string[] = [];

	if (policy === "safe" || policy === "strict") {
		if (deletePayloadField(payload, "prompt_cache_key")) changed.push("prompt_cache_key");
		if (deletePayloadField(payload, "promptCacheKey")) changed.push("promptCacheKey");
	} else if (ensurePromptCacheKey(
		payload,
		opaqueSessionKey(ctx, modelKey),
		isOfficialOpenAIBaseUrl(model.baseUrl) ? undefined : ctx.sessionManager.getSessionId(),
	)) {
		changed.push("prompt_cache_key:add");
	}

	if (policy !== "long") {
		if (deletePayloadField(payload, "prompt_cache_retention")) changed.push("prompt_cache_retention");
		if (deletePayloadField(payload, "promptCacheRetention")) changed.push("promptCacheRetention");
	}

	lastModelKey = modelKey;
	lastPolicy = policy;
	lastRemoved = changed;
	return changed;
}

export default function (pi: ExtensionAPI) {
	pi.on("before_provider_headers", (event, ctx) => {
		const model = ctx.model;
		if (!model || !isOpenAICompatibleApi(model.api) || effectivePolicy(model) !== "strict") return;
		for (const name of AFFINITY_HEADERS) deleteCaseInsensitiveHeader(event.headers, name);
	});

	pi.on("before_provider_request", (event, ctx) => {
		const model = ctx.model;
		if (!model) return;
		const changes = applyPayloadPolicy(event.payload, model, ctx);
		if (isEnabledEnv(process.env[DEBUG_ENV])) {
			console.warn(
				`[cache-compat-guard] ${model.provider}/${model.id} ` +
				`policy=${effectivePolicy(model)} changes=${changes.join(",") || "none"}`,
			);
		}
	});

	pi.registerCommand("cache-compat", {
		description: "Show the effective prompt-cache compatibility policy for the active model",
		handler: async (_args, ctx) => {
			const model = ctx.model;
			if (!model) {
				ctx.ui.notify("No active model", "warning");
				return;
			}
			const modelKey = `${model.provider}/${model.id}`;
			const configured = configuredPolicy(model);
			const effective = effectivePolicy(model);
			const details = lastModelKey === modelKey && lastRemoved.length
				? ` Last request changes: ${lastRemoved.join(", ")}.`
				: "";
			ctx.ui.notify(
				`${modelKey}: configured=${configured}, effective=${effective}.${details}`,
				effective === "strict" ? "warning" : "info",
			);
		},
	});
}

export const __internals_for_tests = {
	asRecord,
	isEnabledEnv,
	normalizePolicy,
	isOpenAICompatibleApi,
	isOfficialOpenAIBaseUrl,
	isPiBuiltInLlamaCppModel,
	deleteCaseInsensitiveHeader,
	configuredPolicy,
	effectivePolicy,
	deletePayloadField,
	ensurePromptCacheKey,
	applyPayloadPolicy,
};
