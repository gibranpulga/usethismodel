-- Endpoint protocol facts are independent of model routes. UNKNOWN is the
-- default; a provider name or vendor family never supplies an implicit fact.
CREATE TABLE provider_protocol_evidence (
  id INTEGER PRIMARY KEY,
  provider_id INTEGER NOT NULL REFERENCES providers(id) ON DELETE CASCADE,
  protocol TEXT NOT NULL,
  state TEXT NOT NULL CHECK (state IN ('YES','NO','UNKNOWN')),
  source_id INTEGER NOT NULL REFERENCES sources(id),
  verified_at TEXT NOT NULL,
  note TEXT NOT NULL,
  UNIQUE(provider_id, protocol)
);
CREATE INDEX idx_provider_protocol_lookup ON provider_protocol_evidence(provider_id,protocol,state);

CREATE TABLE harness_protocol_support (
  id INTEGER PRIMARY KEY,
  harness_id INTEGER NOT NULL REFERENCES harnesses(id) ON DELETE CASCADE,
  protocol TEXT NOT NULL,
  state TEXT NOT NULL CHECK (state IN ('YES','NO','UNKNOWN')),
  access_method TEXT NOT NULL,
  source_id INTEGER NOT NULL REFERENCES sources(id),
  verified_at TEXT NOT NULL,
  note TEXT NOT NULL,
  UNIQUE(harness_id,protocol,access_method)
);
CREATE INDEX idx_harness_protocol_lookup ON harness_protocol_support(harness_id,protocol,state);

INSERT OR IGNORE INTO sources(name,url,source_type,fetched_at,reliability) VALUES
 ('OpenAI API protocol documentation','https://platform.openai.com/docs/api-reference/chat/create','official API documentation','2026-09-30','HIGH'),
 ('OpenAI Responses API documentation','https://platform.openai.com/docs/api-reference/responses/create','official API documentation','2026-09-30','HIGH'),
 ('Anthropic Messages API documentation','https://docs.anthropic.com/en/api/messages','official API documentation','2026-09-30','HIGH'),
 ('Google Gemini API documentation','https://ai.google.dev/api/generate-content','official API documentation','2026-09-30','HIGH'),
 ('DeepSeek API documentation','https://api-docs.deepseek.com/api/create-chat-completion','official API documentation','2026-09-30','HIGH'),
 ('Z.ai API documentation','https://docs.z.ai/api-reference/llm/chat-completion','official API documentation','2026-09-30','HIGH'),
 ('Alibaba Cloud Model Studio API documentation','https://www.alibabacloud.com/help/en/model-studio/getting-started/models','official API documentation','2026-09-30','HIGH'),
 ('Mistral API documentation','https://docs.mistral.ai/api/','official API documentation','2026-09-30','HIGH'),
 ('OpenRouter API documentation','https://openrouter.ai/docs/api-reference/overview','official API documentation','2026-09-30','HIGH'),
 ('OpenCode provider documentation','https://opencode.ai/docs/providers/','official product documentation','2026-09-30','HIGH'),
 ('Pi provider documentation','https://github.com/badlogic/pi-mono/tree/main/packages/coding-agent/docs','official product documentation','2026-09-30','HIGH'),
 ('Hermes provider documentation','https://hermes-agent.nousresearch.com/docs/integrations/providers','official product documentation','2026-09-30','HIGH'),
 ('Codex CLI configuration documentation','https://developers.openai.com/codex/config-reference','official product documentation','2026-09-30','HIGH');

-- Exact protocol claims only. Capabilities describe provider endpoints, not
-- every model available on them. Tool support remains route-specific.
WITH x(provider,protocol,note) AS (VALUES
 ('OpenAI','OPENAI_CHAT_COMPLETIONS','Official Chat Completions endpoint.'),
 ('OpenAI','OPENAI_RESPONSES','Official Responses endpoint.'),
 ('Anthropic','ANTHROPIC_MESSAGES','Official Messages endpoint.'),
 ('Google','GOOGLE_GEMINI_NATIVE','Official Gemini generateContent endpoint.'),
 ('DeepSeek','OPENAI_CHAT_COMPLETIONS','Provider documents its OpenAI-style chat completions endpoint; endpoint compatibility does not establish per-model feature parity.'),
 ('Z.ai','OPENAI_CHAT_COMPLETIONS','Provider documents its OpenAI-compatible chat completion endpoint; model capabilities remain route-specific.'),
 ('Alibaba Cloud','OPENAI_CHAT_COMPLETIONS','Model Studio documents OpenAI-compatible Chat Completions for supported deployments; region and model availability vary.'),
 ('Mistral','OPENAI_CHAT_COMPLETIONS','Official API offers chat completions; additional provider-specific endpoints are not represented here.'),
 ('OpenRouter','OPENAI_CHAT_COMPLETIONS','OpenRouter documents its OpenAI-compatible API endpoint.'),
 ('OpenRouter','ANTHROPIC_MESSAGES','OpenRouter documents an Anthropic-compatible Messages endpoint; model and feature behavior may vary by route.'),
 ('Mistral','MISTRAL_CONVERSATIONS','Official Mistral API supports provider-native conversations and chat streaming.')
)
INSERT INTO provider_protocol_evidence(provider_id,protocol,state,source_id,verified_at,note)
SELECT p.id,x.protocol,'YES',s.id,'2026-09-30',x.note FROM x
JOIN providers p ON lower(p.name)=lower(x.provider)
JOIN sources s ON s.name=CASE x.provider
 WHEN 'OpenAI' THEN 'OpenAI API protocol documentation'
 WHEN 'Anthropic' THEN 'Anthropic Messages API documentation'
 WHEN 'Google' THEN 'Google Gemini API documentation'
 WHEN 'DeepSeek' THEN 'DeepSeek API documentation'
 WHEN 'Z.ai' THEN 'Z.ai API documentation'
 WHEN 'Alibaba Cloud' THEN 'Alibaba Cloud Model Studio API documentation'
 WHEN 'Mistral' THEN 'Mistral API documentation'
ELSE 'OpenRouter API documentation' END;

-- Endpoint feature capabilities are also provider-level facts. A YES means the
-- endpoint accepts the feature for supported models; it does not promise that
-- every route/model implements it.
WITH x(provider,capability,source_name,note) AS (VALUES
 ('OpenAI','STREAMING','OpenAI API protocol documentation','Streaming responses are supported by the documented endpoint; availability and details can differ between Chat Completions and Responses.'),
 ('OpenAI','TOOL_FUNCTION_CALLING','OpenAI API protocol documentation','The documented API exposes tool/function calls; model and endpoint support still applies.'),
 ('Anthropic','STREAMING','Anthropic Messages API documentation','Messages streaming is supported; model and SDK behavior may differ.'),
 ('Anthropic','TOOL_FUNCTION_CALLING','Anthropic Messages API documentation','The Messages API accepts tools; the model must support tool use.'),
 ('Google','STREAMING','Google Gemini API documentation','The Gemini API provides streaming generation methods for supported models.'),
 ('Google','TOOL_FUNCTION_CALLING','Google Gemini API documentation','Gemini function calling is documented; supported models and tools vary.'),
 ('DeepSeek','STREAMING','DeepSeek API documentation','The chat completion endpoint supports streaming output.'),
 ('DeepSeek','TOOL_FUNCTION_CALLING','DeepSeek API documentation','The API documents tool calls for supported models; do not generalize to all model IDs.'),
 ('Z.ai','STREAMING','Z.ai API documentation','The chat completion endpoint supports stream responses.'),
 ('Z.ai','TOOL_FUNCTION_CALLING','Z.ai API documentation','The API documents function calling for supported models; route-level catalog facts remain authoritative.'),
 ('Alibaba Cloud','STREAMING','Alibaba Cloud Model Studio API documentation','Supported Model Studio compatible deployments provide streaming output.'),
 ('Alibaba Cloud','TOOL_FUNCTION_CALLING','Alibaba Cloud Model Studio API documentation','Function calling is supported on documented compatible models; model availability varies by region.'),
 ('Mistral','STREAMING','Mistral API documentation','The provider API documents streaming responses.'),
 ('Mistral','TOOL_FUNCTION_CALLING','Mistral API documentation','The API supports tools on models that expose function calling.'),
 ('OpenRouter','STREAMING','OpenRouter API documentation','Streaming is available where the selected upstream model supports it.'),
 ('OpenRouter','TOOL_FUNCTION_CALLING','OpenRouter API documentation','Tool use depends on the exact model and upstream route; catalog route flags take precedence.')
)
INSERT INTO provider_protocol_evidence(provider_id,protocol,state,source_id,verified_at,note)
SELECT p.id,x.capability,'YES',s.id,'2026-09-30',x.note FROM x
JOIN providers p ON lower(p.name)=lower(x.provider)
JOIN sources s ON s.name=x.source_name;

-- Harness support is an explicit protocol/access pairing from product docs.
WITH x(harness,protocol,access,note) AS (VALUES
 ('OpenCode','OPENAI_CHAT_COMPLETIONS','NATIVE_PROVIDER','Built-in provider SDK support.'),
 ('OpenCode','OPENAI_RESPONSES','NATIVE_PROVIDER','OpenAI provider supports the Responses API.'),
 ('OpenCode','ANTHROPIC_MESSAGES','NATIVE_PROVIDER','Built-in Anthropic provider.'),
 ('OpenCode','OPENAI_CHAT_COMPLETIONS','CUSTOM_OPENAI_COMPATIBLE','Custom OpenAI-compatible provider configuration.'),
 ('Pi','OPENAI_CHAT_COMPLETIONS','NATIVE_PROVIDER','Built-in OpenAI provider.'),
 ('Pi','OPENAI_RESPONSES','NATIVE_PROVIDER','Built-in Responses provider support.'),
 ('Pi','ANTHROPIC_MESSAGES','NATIVE_PROVIDER','Built-in Anthropic provider.'),
 ('Pi','GOOGLE_GEMINI_NATIVE','NATIVE_PROVIDER','Built-in Google Gemini provider.'),
 ('Pi','MISTRAL_CONVERSATIONS','NATIVE_PROVIDER','Built-in Mistral provider uses the Mistral Conversations API.'),
 ('Pi','OPENAI_CHAT_COMPLETIONS','CUSTOM_OPENAI_COMPATIBLE','Custom models can select OpenAI Completions transport.'),
 ('Pi','ANTHROPIC_MESSAGES','CUSTOM_ANTHROPIC_COMPATIBLE','Custom models can select Anthropic Messages transport.'),
 ('Hermes Agent','OPENAI_CHAT_COMPLETIONS','NATIVE_PROVIDER','Provider profiles and custom provider use the OpenAI-compatible chat transport.'),
 ('Hermes Agent','OPENAI_CHAT_COMPLETIONS','CUSTOM_OPENAI_COMPATIBLE','Custom provider profile accepts a base URL and OpenAI-compatible chat transport.'),
 ('Claude Code','ANTHROPIC_MESSAGES','NATIVE_PROVIDER','Native Anthropic Messages support. Third-party gateways require Anthropic-format behavior and compatible Claude model IDs.'),
 ('Claude Code','ANTHROPIC_MESSAGES','CUSTOM_ANTHROPIC_COMPATIBLE','Anthropic-format gateway mode is documented, with model and feature compatibility restrictions.'),
 ('Codex CLI','OPENAI_RESPONSES','NATIVE_PROVIDER','Codex native API path uses the Responses protocol.'),
 ('Codex CLI','OPENAI_RESPONSES','CUSTOM_OPENAI_COMPATIBLE','Custom provider mode requires a Responses-compatible endpoint; generic Chat Completions is insufficient.')
)
INSERT INTO harness_protocol_support(harness_id,protocol,state,access_method,source_id,verified_at,note)
SELECT h.id,x.protocol,'YES',x.access,s.id,'2026-09-30',x.note FROM x
JOIN harnesses h ON h.name=x.harness
JOIN sources s ON s.name=CASE x.harness WHEN 'OpenCode' THEN 'OpenCode official docs'
 WHEN 'Pi' THEN 'Pi official repository docs' WHEN 'Hermes Agent' THEN 'Hermes Agent official docs'
 WHEN 'Claude Code' THEN 'Claude Code official docs'
 ELSE 'Codex CLI official docs' END;
