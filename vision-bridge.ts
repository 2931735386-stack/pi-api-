// Managed by pi-api-switcher. Remove this line to prevent automatic updates.
import { uuidv7, type ImageContent, type Model, type TextContent, type Usage } from "@earendil-works/pi-ai";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { readFile } from "node:fs/promises";
import { join } from "node:path";

type VisionBridgeConfig = {
	provider: string;
	modelId: string;
};

type ModelsFile = {
	providers?: Record<string, {
		models?: Array<{
			id?: string;
			visionModel?: string;
		}>;
	}>;
};

const CONFIG_FILE = join(process.env.USERPROFILE ?? process.env.HOME ?? "", ".pi", "agent", "models.json");
const MAX_DESCRIPTION_CHARS = 24_000;

function textFromResponse(content: Array<{ type: string; text?: string }>): string {
	return content
		.filter((block): block is { type: "text"; text: string } => block.type === "text" && typeof block.text === "string")
		.map((block) => block.text)
		.join("\n")
		.trim();
}

function parseVisionModel(value: unknown): VisionBridgeConfig | undefined {
	if (typeof value !== "string") return undefined;
	const first = value.split("|")[0]?.trim();
	if (!first) return undefined;

	const separator = first.indexOf(":");
	if (separator <= 0 || separator === first.length - 1) return undefined;

	return {
		provider: first.slice(0, separator).trim(),
		modelId: first.slice(separator + 1).trim(),
	};
}

async function configuredVisionModel(activeModel: Model): Promise<VisionBridgeConfig | undefined> {
	try {
		const config = JSON.parse(await readFile(CONFIG_FILE, "utf8")) as ModelsFile;
		const configuredModel = config.providers?.[activeModel.provider]?.models?.find(
			(model) => model.id === activeModel.id,
		);
		return parseVisionModel(configuredModel?.visionModel);
	} catch {
		return undefined;
	}
}

async function describeImages(
	activeModel: Model,
	images: ImageContent[],
	userText: string,
	ctx: ExtensionContext,
): Promise<{ description: string; usage?: Usage; vision: VisionBridgeConfig }> {
	const vision = await configuredVisionModel(activeModel);
	if (!vision) {
		throw new Error(`No visionModel is configured for ${activeModel.provider}:${activeModel.id}`);
	}

	const model = ctx.modelRegistry.find(vision.provider, vision.modelId);
	if (!model) {
		throw new Error(`Configured vision model ${vision.provider}:${vision.modelId} is unavailable`);
	}
	if (!model.input.includes("image")) {
		throw new Error(`Configured vision model ${vision.provider}:${vision.modelId} is not marked as image-capable`);
	}
	if (!ctx.modelRegistry.hasConfiguredAuth(model)) {
		throw new Error(`No credentials are configured for vision model ${vision.provider}:${vision.modelId}`);
	}

	const instruction = [
		"Analyze the attached image or images for a downstream text-only assistant.",
		"Describe all information relevant to the user's request, including visible text, layout, objects, relationships, numbers, errors, and uncertainty.",
		"Do not claim to have performed actions beyond visual analysis.",
		userText.trim() ? `User request: ${userText.trim()}` : "User request: analyze the attached image.",
	].join("\n");

	const response = await ctx.modelRegistry.complete(
		model,
		{
			messages: [{
				role: "user",
				content: [{ type: "text", text: instruction }, ...images],
				timestamp: Date.now(),
			}],
		},
		{
			maxTokens: 4096,
			cacheRetention: "none",
			sessionId: uuidv7(),
			signal: ctx.signal ?? AbortSignal.timeout(90_000),
		},
	);

	const description = textFromResponse(response.content);
	if (!description) {
		throw new Error(`Vision model ${vision.provider}:${vision.modelId} returned no text`);
	}

	return { description: description.slice(0, MAX_DESCRIPTION_CHARS), usage: response.usage, vision };
}

function bridgeText(description: string, vision: VisionBridgeConfig): string {
	return [
		"[Vision bridge result]",
		`The following is an image analysis produced by ${vision.provider}:${vision.modelId}. Treat it as the visual input for this request.`,
		description,
		"[End vision bridge result]",
	].join("\n");
}

function imageFailureText(error: unknown): string {
	const message = error instanceof Error ? error.message : String(error);
	return [
		"[Vision bridge unavailable]",
		`The attached image was not sent to the text-only model. ${message}`,
		"[End vision bridge unavailable]",
	].join("\n");
}

function isTextOnly(model: Model | undefined): model is Model {
	return !!model && !model.input.includes("image");
}

export default function (pi: ExtensionAPI) {
	pi.on("input", async (event, ctx) => {
		if (!event.images?.length || !isTextOnly(ctx.model)) return;

		try {
			const result = await describeImages(ctx.model, event.images, event.text, ctx);
			if (ctx.hasUI) ctx.ui.setStatus("vision-bridge", `Vision: ${result.vision.provider}:${result.vision.modelId}`);
			return {
				action: "transform",
				text: `${event.text}\n\n${bridgeText(result.description, result.vision)}`.trim(),
				images: [],
			};
		} catch (error) {
			if (ctx.hasUI) ctx.ui.setStatus("vision-bridge", "Vision bridge failed");
			return {
				action: "transform",
				text: `${event.text}\n\n${imageFailureText(error)}`.trim(),
				images: [],
			};
		}
	});

	pi.on("tool_result", async (event, ctx) => {
		if (!isTextOnly(ctx.model)) return;
		const images = event.content.filter((block): block is ImageContent => block.type === "image");
		if (!images.length) return;

		const existingText = event.content
			.filter((block): block is TextContent => block.type === "text")
			.map((block) => block.text)
			.join("\n");

		try {
			const result = await describeImages(ctx.model, images, existingText, ctx);
			return {
				content: [{ type: "text", text: `${existingText}\n\n${bridgeText(result.description, result.vision)}`.trim() }],
				usage: result.usage,
			};
		} catch (error) {
			return {
				content: [{ type: "text", text: `${existingText}\n\n${imageFailureText(error)}`.trim() }],
			};
		}
	});

	pi.registerCommand("vision-bridge", {
		description: "Show the vision bridge configured for the active text-only model",
		handler: async (_args, ctx) => {
			if (!ctx.model) {
				ctx.ui.notify("No active model", "warning");
				return;
			}
			if (!isTextOnly(ctx.model)) {
				ctx.ui.notify(`${ctx.model.provider}:${ctx.model.id} already accepts images`, "info");
				return;
			}
			const vision = await configuredVisionModel(ctx.model);
			ctx.ui.notify(
				vision
					? `${ctx.model.provider}:${ctx.model.id} -> ${vision.provider}:${vision.modelId}`
					: `No visionModel is configured for ${ctx.model.provider}:${ctx.model.id}`,
				vision ? "info" : "warning",
			);
		},
	});
}
