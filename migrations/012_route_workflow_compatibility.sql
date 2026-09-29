-- Route-specific harness evidence and workflow/tool integration registry.
-- These records intentionally keep model access, MCP hosting, provider tool
-- support, and observed reliability separate.

ALTER TABLE harnesses ADD COLUMN current_version TEXT;
ALTER TABLE harnesses ADD COLUMN version_verified_at TEXT;

CREATE TABLE harness_claims (
  id INTEGER PRIMARY KEY,
  harness_id INTEGER NOT NULL REFERENCES harnesses(id) ON DELETE CASCADE,
  claim_key TEXT NOT NULL,
  claim_value TEXT NOT NULL,
  note TEXT,
  source_id INTEGER NOT NULL REFERENCES sources(id),
  verified_at TEXT NOT NULL,
  UNIQUE(harness_id, claim_key)
);

CREATE TABLE harness_access_methods (
  id INTEGER PRIMARY KEY,
  harness_id INTEGER NOT NULL REFERENCES harnesses(id) ON DELETE CASCADE,
  access_method TEXT NOT NULL CHECK (access_method IN (
    'API_KEY','OPENROUTER','NATIVE_PROVIDER_LOGIN','CODING_SUBSCRIPTION',
    'CHATGPT_CODEX_SUBSCRIPTION','OAUTH','LOCAL_ENDPOINT',
    'CUSTOM_OPENAI_COMPATIBLE','CUSTOM_ANTHROPIC_COMPATIBLE','COMMUNITY_ADAPTER_PROXY'
  )),
  state TEXT NOT NULL CHECK (state IN ('YES','NO','UNKNOWN')),
  note TEXT,
  source_id INTEGER NOT NULL REFERENCES sources(id),
  verified_at TEXT NOT NULL,
  UNIQUE(harness_id, access_method)
);

CREATE TABLE workflows (
  id INTEGER PRIMARY KEY,
  slug TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL UNIQUE,
  description TEXT NOT NULL,
  caution TEXT,
  source_id INTEGER REFERENCES sources(id),
  verified_at TEXT NOT NULL
);

CREATE TABLE workflow_integrations (
  id INTEGER PRIMARY KEY,
  workflow_id INTEGER NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  repository_url TEXT NOT NULL,
  transport TEXT NOT NULL,
  os_requirements TEXT,
  locality TEXT NOT NULL CHECK (locality IN ('LOCAL','REMOTE','BOTH','UNKNOWN')),
  tools_exposed TEXT NOT NULL,
  maintenance_status TEXT NOT NULL CHECK (maintenance_status IN ('ACTIVE','INACTIVE','UNKNOWN')),
  maintenance_note TEXT,
  source_id INTEGER NOT NULL REFERENCES sources(id),
  verified_at TEXT NOT NULL,
  UNIQUE(workflow_id, name)
);

CREATE TABLE workflow_harness_compatibility (
  id INTEGER PRIMARY KEY,
  integration_id INTEGER NOT NULL REFERENCES workflow_integrations(id) ON DELETE CASCADE,
  harness_id INTEGER NOT NULL REFERENCES harnesses(id) ON DELETE CASCADE,
  state TEXT NOT NULL CHECK (state IN ('YES','CONFIGURATION','PARTIAL','NO','UNKNOWN')),
  reason TEXT NOT NULL,
  source_id INTEGER NOT NULL REFERENCES sources(id),
  verified_at TEXT NOT NULL,
  UNIQUE(integration_id, harness_id)
);

CREATE TABLE route_compatibility_evidence (
  id INTEGER PRIMARY KEY,
  harness_id INTEGER NOT NULL REFERENCES harnesses(id) ON DELETE CASCADE,
  offering_id INTEGER NOT NULL REFERENCES provider_offerings(id) ON DELETE CASCADE,
  capability TEXT NOT NULL DEFAULT 'TOOLS',
  access_method TEXT NOT NULL,
  harness_can_use_model TEXT NOT NULL CHECK (harness_can_use_model IN ('YES','NO','UNKNOWN')),
  harness_supports_mcp TEXT NOT NULL CHECK (harness_supports_mcp IN ('YES','NO','UNKNOWN')),
  provider_tool_calls TEXT NOT NULL CHECK (provider_tool_calls IN ('YES','NO','UNKNOWN')),
  tool_reliability TEXT NOT NULL CHECK (tool_reliability IN ('RELIABLE','MIXED','UNVERIFIED','UNKNOWN')),
  mcp_workflow_status TEXT NOT NULL CHECK (mcp_workflow_status IN (
    'COMPATIBLE','COMPATIBLE_WITH_CONFIGURATION','PARTIAL','UNKNOWN','NOT_COMPATIBLE'
  )),
  reason TEXT NOT NULL,
  source_id INTEGER NOT NULL REFERENCES sources(id),
  verified_at TEXT NOT NULL,
  UNIQUE(harness_id, offering_id, capability)
);

CREATE INDEX idx_route_compatibility_harness ON route_compatibility_evidence(harness_id, offering_id);
CREATE INDEX idx_workflow_integrations_workflow ON workflow_integrations(workflow_id);

INSERT OR IGNORE INTO sources(name,url,source_type,fetched_at,reliability) VALUES
 ('Epic Unreal MCP documentation','https://dev.epicgames.com/documentation/unreal-engine/unreal-mcp-in-unreal-editor','official documentation','2026-09-29','HIGH'),
 ('IvanMurzak Unreal MCP repository','https://github.com/IvanMurzak/Unreal-MCP','official repository','2026-09-29','HIGH'),
 ('ChiR24 Unreal MCP repository','https://github.com/ChiR24/Unreal_mcp','official repository','2026-09-29','HIGH'),
 ('UnrealMCP x0cipher repository','https://github.com/x0cipher/unreal-mcp','official repository','2026-09-29','HIGH'),
 ('GenOrca Unreal MCP repository','https://github.com/GenOrca/unreal-mcp','official repository','2026-09-29','HIGH'),
 ('Bonfire REAPER MCP repository','https://github.com/bonfire-systems/reaper-mcp','official repository','2026-09-29','HIGH'),
 ('TwelveTake REAPER MCP repository','https://github.com/TwelveTake-Studios/reaper-mcp','official repository','2026-09-29','HIGH'),
 ('ReaMCP repository','https://github.com/danielkinahan/ReaMCP','official repository','2026-09-29','HIGH'),
 ('MCP reference servers','https://github.com/modelcontextprotocol/servers','official repository','2026-09-29','HIGH'),
 ('GitHub MCP Server','https://github.com/github/github-mcp-server','official repository','2026-09-29','HIGH'),
 ('Playwright MCP','https://github.com/microsoft/playwright-mcp','official repository','2026-09-29','HIGH'),
 ('MCP transports specification','https://modelcontextprotocol.io/specification/2025-11-25/basic/transports','official documentation','2026-09-29','HIGH'),
 ('Hermes installed version inspection','https://github.com/NousResearch/hermes-agent/tree/6a6aacc1cb60fa5d7fd4ef1abcd5879116f25eca','local installation inspection','2026-09-29','HIGH');

INSERT INTO workflows(slug,name,description,caution,source_id,verified_at) VALUES
 ('unreal-engine','Unreal Engine MCP','Use an MCP server plus an Unreal Editor bridge/plugin to inspect and modify Unreal projects.','There is no single canonical Unreal MCP. Implementations differ in engine version, bridge architecture, operating-system requirements, tool surface, and maintenance.',(SELECT id FROM sources WHERE name='UnrealMCP x0cipher repository'),'2026-09-29'),
 ('reaper','REAPER MCP','Use an MCP server plus a REAPER ReaScript, extension, distant API, socket, or file bridge to control a live DAW project.','Compatibility depends on the exact server and bridge implementation; REAPER support is not a property of the model alone.',(SELECT id FROM sources WHERE name='Bonfire REAPER MCP repository'),'2026-09-29'),
 ('filesystem','Filesystem','Read, search, edit, move, and manage files within configured roots.',NULL,(SELECT id FROM sources WHERE name='MCP reference servers'),'2026-09-29'),
 ('shell-ssh','Shell / SSH','Run local shell commands or administer a remote machine through a deliberately scoped tool or native harness shell.', 'Shell and SSH tools can mutate systems; host support does not imply safe sandboxing.',(SELECT id FROM sources WHERE name='MCP transports specification'),'2026-09-29'),
 ('browser','Browser','Automate browser pages, accessibility snapshots, navigation, and interaction.',NULL,(SELECT id FROM sources WHERE name='Playwright MCP'),'2026-09-29'),
 ('git-github','Git / GitHub','Inspect and modify local Git repositories or use GitHub APIs for repository, issue, pull-request, and workflow tasks.',NULL,(SELECT id FROM sources WHERE name='GitHub MCP Server'),'2026-09-29'),
 ('remote-mcp','Generic remote MCP','Connect a host to a remote MCP server over Streamable HTTP or legacy HTTP+SSE where supported.',NULL,(SELECT id FROM sources WHERE name='MCP transports specification'),'2026-09-29');

INSERT INTO workflow_integrations(workflow_id,name,repository_url,transport,os_requirements,locality,tools_exposed,maintenance_status,maintenance_note,source_id,verified_at) VALUES
 ((SELECT id FROM workflows WHERE slug='unreal-engine'),'Epic Unreal MCP (UE 5.8 Experimental)','https://dev.epicgames.com/documentation/unreal-engine/unreal-mcp-in-unreal-editor','Embedded Streamable HTTP at 127.0.0.1:8000/mcp','Unreal Engine 5.8; engine-supported editor desktop platforms','LOCAL','Actors, lighting, materials, Slate inspection, automation tests, extensible toolsets','ACTIVE','Official Epic implementation, but Experimental and one of several materially different servers.',(SELECT id FROM sources WHERE name='Epic Unreal MCP documentation'),'2026-09-29'),
 ((SELECT id FROM workflows WHERE slug='unreal-engine'),'IvanMurzak/Unreal-MCP','https://github.com/IvanMurzak/Unreal-MCP','stdio or HTTP MCP; authenticated .NET sidecar and SignalR bridge','Unreal Engine on Win64, macOS, or Linux; .NET 9 sidecar','BOTH','61 tools across actors, assets, levels, Blueprints, C++, screenshots, prompts and resources','ACTIVE','Beta release 0.19.0; hosted or self-hosted server options.',(SELECT id FROM sources WHERE name='IvanMurzak Unreal MCP repository'),'2026-09-29'),
 ((SELECT id FROM workflows WHERE slug='unreal-engine'),'ChiR24/Unreal_mcp','https://github.com/ChiR24/Unreal_mcp','Embedded Streamable HTTP/SSE or Node stdio bridge','Unreal Engine 5.0–5.7 documented; desktop plugin build required','BOTH','36 namespace tool families for actors, assets, editor, levels, pipelines, lighting, navigation and Python','ACTIVE','Separate implementation with optional LAN binding and capability token.',(SELECT id FROM sources WHERE name='ChiR24 Unreal MCP repository'),'2026-09-29'),
 ((SELECT id FROM workflows WHERE slug='unreal-engine'),'x0cipher/unreal-mcp','https://github.com/x0cipher/unreal-mcp','MCP stdio; local TCP bridge to Unreal plugin','Unreal Engine 5.7; Windows C++ toolchain documented; Python 3.10+','LOCAL','Execute Unreal Python, actor/asset/material/Blueprint editing, editor logs','ACTIVE','Repository activity and requirements checked on verification date.',(SELECT id FROM sources WHERE name='UnrealMCP x0cipher repository'),'2026-09-29'),
 ((SELECT id FROM workflows WHERE slug='unreal-engine'),'GenOrca/unreal-mcp','https://github.com/GenOrca/unreal-mcp','MCP stdio; Unreal C++/Python bridge','Unreal Engine 5; prebuilt releases vary by engine/OS; source builds need a C++ toolchain','LOCAL','Editor automation and extensible Python/C++ tools','ACTIVE','Separate community implementation; do not treat as interchangeable with other Unreal MCP projects.',(SELECT id FROM sources WHERE name='GenOrca Unreal MCP repository'),'2026-09-29'),
 ((SELECT id FROM workflows WHERE slug='reaper'),'bonfire-systems/reaper-mcp','https://github.com/bonfire-systems/reaper-mcp','MCP stdio; python-reapy distant API bridge','REAPER running; Python 3.10+; distant API enabled','LOCAL','58 tools: projects, tracks, MIDI, FX, audio, mixing, rendering, mastering, analysis','ACTIVE','Project repository checked on verification date.',(SELECT id FROM sources WHERE name='Bonfire REAPER MCP repository'),'2026-09-29'),
 ((SELECT id FROM workflows WHERE slug='reaper'),'TwelveTake-Studios/reaper-mcp','https://github.com/TwelveTake-Studios/reaper-mcp','MCP stdio; file-based Lua ReaScript bridge','REAPER on Windows, macOS, or Linux; Python 3.10+','LOCAL','176 documented production tools spanning mixing, mastering, MIDI, routing, automation, and rendering','ACTIVE','Release 1.8.0 checked on 2026-09-29; HTTP was removed because it was not reliable.',(SELECT id FROM sources WHERE name='TwelveTake REAPER MCP repository'),'2026-09-29'),
 ((SELECT id FROM workflows WHERE slug='reaper'),'danielkinahan/ReaMCP','https://github.com/danielkinahan/ReaMCP','MCP stdio; JSON-RPC TCP bridge on localhost','REAPER with ReaPack and mavriq-lua-sockets; Python 3.10+','LOCAL','Project inspection/editing, mixing and loudness-oriented tools','ACTIVE','Distinct socket-bridge approach.',(SELECT id FROM sources WHERE name='ReaMCP repository'),'2026-09-29'),
 ((SELECT id FROM workflows WHERE slug='filesystem'),'Reference filesystem server','https://github.com/modelcontextprotocol/servers/tree/main/src/filesystem','MCP stdio','Node.js; Windows, macOS, or Linux paths','LOCAL','Read/write files, directories, search, metadata, edits, configured-root control','ACTIVE','Official reference server.',(SELECT id FROM sources WHERE name='MCP reference servers'),'2026-09-29'),
 ((SELECT id FROM workflows WHERE slug='shell-ssh'),'Harness-native shell and SSH','https://modelcontextprotocol.io/specification/2025-11-25/basic/transports','Native harness tools or a separately selected MCP server','Depends on the harness and target host','BOTH','Commands, processes, terminals, and remote administration; exact surface varies','UNKNOWN','Registry entry describes an approach, not one canonical MCP server.',(SELECT id FROM sources WHERE name='MCP transports specification'),'2026-09-29'),
 ((SELECT id FROM workflows WHERE slug='browser'),'Microsoft Playwright MCP','https://github.com/microsoft/playwright-mcp','MCP stdio or remote HTTP configuration','Node.js and a supported browser','BOTH','Navigation, accessibility snapshots, page interaction, tabs, screenshots and browser state','ACTIVE','Official Microsoft project.',(SELECT id FROM sources WHERE name='Playwright MCP'),'2026-09-29'),
 ((SELECT id FROM workflows WHERE slug='git-github'),'Reference Git server','https://github.com/modelcontextprotocol/servers/tree/main/src/git','MCP stdio','Python plus a local Git repository','LOCAL','Read, search, diff, stage, commit, branch and repository operations','ACTIVE','Official reference server.',(SELECT id FROM sources WHERE name='MCP reference servers'),'2026-09-29'),
 ((SELECT id FROM workflows WHERE slug='git-github'),'GitHub MCP Server','https://github.com/github/github-mcp-server','MCP stdio or remote HTTP','GitHub authentication; Docker or binary for local mode','BOTH','Repositories, issues, pull requests, code, workflows and GitHub API operations','ACTIVE','Official GitHub project.',(SELECT id FROM sources WHERE name='GitHub MCP Server'),'2026-09-29'),
 ((SELECT id FROM workflows WHERE slug='remote-mcp'),'Generic remote MCP server','https://modelcontextprotocol.io/specification/2025-11-25/basic/transports','Streamable HTTP; legacy HTTP+SSE depends on host','Network access and any server-specific OAuth or bearer authentication','REMOTE','Server-defined MCP tools, resources, and prompts','ACTIVE','Transport is standardized; each server still determines auth and capabilities.',(SELECT id FROM sources WHERE name='MCP transports specification'),'2026-09-29');

-- Locally inspected Hermes Agent installation: release 0.20.0 at the pinned
-- commit below. Values describe code/config architecture, never credentials.
UPDATE harnesses SET current_version='0.20.0',version_verified_at='2026-09-29',
  website_url='https://hermes-agent.nousresearch.com/docs',supports_mcp=1,
  interfaces='CLI,TUI,desktop,API',headless_support='YES',ssh_remote_support='YES',
  openrouter_support='YES',custom_openai_compatible='YES',local_model_support='YES'
WHERE name='Hermes Agent';

INSERT INTO harness_claims(harness_id,claim_key,claim_value,note,source_id,verified_at) VALUES
 ((SELECT id FROM harnesses WHERE name='Hermes Agent'),'built_in_providers','actual, ai-gateway, Alibaba, Alibaba Coding Plan, Anthropic, Arcee, Azure Foundry, Bedrock, Copilot, DeepInfra, DeepSeek, Fireworks, Gemini, Hugging Face, Kilo, Kimi Coding, MiniMax, Nous, Novita, NVIDIA, Ollama Cloud, OpenAI Codex, OpenCode Zen, OpenRouter, Qwen OAuth, StepFun, Upstage, Vertex, xAI, Xiaomi, Z.ai','Read from the installed provider plugin registry.',(SELECT id FROM sources WHERE name='Hermes installed version inspection'),'2026-09-29'),
 ((SELECT id FROM harnesses WHERE name='Hermes Agent'),'openai_compatible','YES','Custom provider plugins expose configurable base URLs and the OpenAI-compatible chat transport.',(SELECT id FROM sources WHERE name='Hermes installed version inspection'),'2026-09-29'),
 ((SELECT id FROM harnesses WHERE name='Hermes Agent'),'anthropic_compatible','PARTIAL','Native Anthropic provider exists; arbitrary Anthropic-compatible endpoints were not established by the installed configuration architecture.',(SELECT id FROM sources WHERE name='Hermes installed version inspection'),'2026-09-29'),
 ((SELECT id FROM harnesses WHERE name='Hermes Agent'),'mcp_transports','stdio, Streamable HTTP, SSE','Confirmed in installed tools/mcp_tool.py.',(SELECT id FROM sources WHERE name='Hermes installed version inspection'),'2026-09-29'),
 ((SELECT id FROM harnesses WHERE name='Hermes Agent'),'tool_support','YES','Native tools plus discovered MCP tools feed the model tool loop.',(SELECT id FROM sources WHERE name='Hermes installed version inspection'),'2026-09-29'),
 ((SELECT id FROM harnesses WHERE name='Hermes Agent'),'installed_architecture','ProviderProfile plugin registry; per-profile config; CLI/TUI/desktop/API service; MCP server registry','Inspected version 0.20.0, commit 6a6aacc1cb60fa5d7fd4ef1abcd5879116f25eca on the VPS.',(SELECT id FROM sources WHERE name='Hermes installed version inspection'),'2026-09-29');

INSERT INTO harness_access_methods(harness_id,access_method,state,note,source_id,verified_at) VALUES
 ((SELECT id FROM harnesses WHERE name='Hermes Agent'),'API_KEY','YES','Bundled provider profiles accept provider API keys.',(SELECT id FROM sources WHERE name='Hermes installed version inspection'),'2026-09-29'),
 ((SELECT id FROM harnesses WHERE name='Hermes Agent'),'OPENROUTER','YES','Bundled OpenRouter provider profile.',(SELECT id FROM sources WHERE name='Hermes installed version inspection'),'2026-09-29'),
 ((SELECT id FROM harnesses WHERE name='Hermes Agent'),'OAUTH','YES','Installed provider set includes Qwen OAuth, Copilot and OpenAI Codex login flows.',(SELECT id FROM sources WHERE name='Hermes installed version inspection'),'2026-09-29'),
 ((SELECT id FROM harnesses WHERE name='Hermes Agent'),'CODING_SUBSCRIPTION','YES','Alibaba Coding Plan and Kimi Coding provider profiles are installed.',(SELECT id FROM sources WHERE name='Hermes installed version inspection'),'2026-09-29'),
 ((SELECT id FROM harnesses WHERE name='Hermes Agent'),'CHATGPT_CODEX_SUBSCRIPTION','YES','Installed OpenAI Codex provider and authentication flow.',(SELECT id FROM sources WHERE name='Hermes installed version inspection'),'2026-09-29'),
 ((SELECT id FROM harnesses WHERE name='Hermes Agent'),'LOCAL_ENDPOINT','YES','Custom/local OpenAI-compatible base URLs are supported.',(SELECT id FROM sources WHERE name='Hermes installed version inspection'),'2026-09-29'),
 ((SELECT id FROM harnesses WHERE name='Hermes Agent'),'CUSTOM_OPENAI_COMPATIBLE','YES','Custom provider profile accepts a base URL and model catalog.',(SELECT id FROM sources WHERE name='Hermes installed version inspection'),'2026-09-29'),
 ((SELECT id FROM harnesses WHERE name='Hermes Agent'),'CUSTOM_ANTHROPIC_COMPATIBLE','UNKNOWN','Native Anthropic is present; generic Anthropic-compatible base URL support was not verified.',(SELECT id FROM sources WHERE name='Hermes installed version inspection'),'2026-09-29');

INSERT OR IGNORE INTO sources(name,url,source_type,fetched_at,reliability) VALUES
 ('Codex CLI official docs','https://developers.openai.com/codex/config-reference','official documentation','2026-09-29','HIGH'),
 ('Claude Code official docs','https://code.claude.com/docs/en/llm-gateway','official documentation','2026-09-29','HIGH'),
 ('OpenCode official docs','https://opencode.ai/docs/providers','official documentation','2026-09-29','HIGH'),
 ('Pi official repository docs','https://github.com/earendil-works/pi/tree/main/packages/coding-agent/docs','official repository','2026-09-29','HIGH'),
 ('Qwen Code official docs','https://github.com/QwenLM/qwen-code/blob/main/docs/users/configuration/model-providers.md','official repository','2026-09-29','HIGH'),
 ('Gemini CLI official docs','https://github.com/google-gemini/gemini-cli/tree/main/docs','official repository','2026-09-29','HIGH'),
 ('Goose official docs','https://github.com/aaif-goose/goose/blob/main/documentation/docs/getting-started/providers.md','official repository','2026-09-29','HIGH'),
 ('Cline official docs','https://docs.cline.bot/provider-config/other-30-plus-providers','official documentation','2026-09-29','HIGH'),
 ('Roo Code archived docs','https://github.com/RooCodeInc/Roo-Code/tree/main/apps/docs/docs','official archived repository','2026-09-29','HIGH'),
 ('Aider official docs','https://aider.chat/docs/llms.html','official documentation','2026-09-29','HIGH'),
 ('Continue official docs','https://docs.continue.dev/customize/model-providers/overview','official documentation','2026-09-29','HIGH'),
 ('ZCode official docs','https://zcode.z.ai/en/docs/configuration','official documentation','2026-09-29','HIGH'),
 ('Hermes Agent official docs','https://hermes-agent.nousresearch.com/docs/integrations/providers','official documentation','2026-09-29','HIGH'),
 ('Zed official docs','https://zed.dev/docs/ai/use-api-access','official documentation','2026-09-29','HIGH');

UPDATE harnesses SET current_version='0.159.1',version_verified_at='2026-09-29',supports_mcp=1,website_url='https://developers.openai.com/codex/',interfaces='CLI,TUI,desktop,IDE,SDK',headless_support='YES',ssh_remote_support='YES',openrouter_support='YES',custom_openai_compatible='YES',local_model_support='YES',login_requirement='ChatGPT/Codex subscription or API key' WHERE name='Codex CLI';
UPDATE harnesses SET current_version='2.1.285',version_verified_at='2026-09-29',supports_mcp=1,website_url='https://code.claude.com/docs/',interfaces='CLI,TUI,IDE,SDK,web remote control',headless_support='YES',ssh_remote_support='YES',openrouter_support='YES',custom_openai_compatible='NO',local_model_support='NO',login_requirement='Claude subscription, API key, or cloud credentials' WHERE name='Claude Code';
UPDATE harnesses SET current_version='1.18.33',version_verified_at='2026-09-29',supports_mcp=1,website_url='https://opencode.ai/docs/',interfaces='CLI,TUI,desktop,web,IDE,ACP',headless_support='YES',ssh_remote_support='YES',openrouter_support='YES',custom_openai_compatible='YES',local_model_support='YES',login_requirement='API key, OAuth, or supported coding subscription' WHERE name='OpenCode';
UPDATE harnesses SET current_version='0.99.1',version_verified_at='2026-09-29',supports_mcp=1,website_url='https://github.com/earendil-works/pi',interfaces='CLI,TUI,JSON,RPC,SDK',headless_support='YES',ssh_remote_support='YES',openrouter_support='YES',custom_openai_compatible='YES',local_model_support='YES',login_requirement='API key, OAuth, or supported subscription login' WHERE name='Pi';
UPDATE harnesses SET current_version='0.24.7',version_verified_at='2026-09-29',supports_mcp=1,website_url='https://qwenlm.github.io/qwen-code-docs/',interfaces='CLI,TUI,ACP,HTTP service,web shell,IDE,desktop',headless_support='YES',ssh_remote_support='YES',openrouter_support='YES',custom_openai_compatible='YES',local_model_support='YES',login_requirement='API key or Alibaba Coding/Token Plan' WHERE name='Qwen Code';
UPDATE harnesses SET current_version='0.61.0',version_verified_at='2026-09-29',supports_mcp=1,website_url='https://geminicli.com/docs/',interfaces='CLI,TUI',headless_support='YES',ssh_remote_support='YES',openrouter_support='NO',custom_openai_compatible='NO',local_model_support='UNKNOWN',login_requirement='Gemini API key, Vertex credentials, or enterprise Code Assist' WHERE name='Gemini CLI';
UPDATE harnesses SET current_version='1.52.0',version_verified_at='2026-09-29',supports_mcp=1,website_url='https://block.github.io/goose/',interfaces='CLI,desktop,API,ACP',headless_support='YES',ssh_remote_support='YES',openrouter_support='YES',custom_openai_compatible='YES',local_model_support='YES',login_requirement='API key or ACP/subscription provider' WHERE name='Goose';
UPDATE harnesses SET current_version='VS Code 4.1.21; CLI 3.0.65; Desktop 0.0.37',version_verified_at='2026-09-29',supports_mcp=1,website_url='https://docs.cline.bot/',interfaces='IDE,CLI,TUI,desktop,SDK',headless_support='YES',ssh_remote_support='YES',openrouter_support='YES',custom_openai_compatible='YES',local_model_support='YES',login_requirement='API key, OAuth, or supported subscription login' WHERE name='Cline';
UPDATE harnesses SET current_version='VS Code 3.54.0; CLI 0.1.17 (archived)',version_verified_at='2026-09-29',supports_mcp=1,website_url='https://github.com/RooCodeInc/Roo-Code',interfaces='IDE,CLI,TUI',headless_support='YES',ssh_remote_support='YES',openrouter_support='YES',custom_openai_compatible='YES',local_model_support='YES',login_requirement='API key or ChatGPT subscription OAuth' WHERE name='Roo Code';
UPDATE harnesses SET current_version='PyPI 0.86.2; GitHub latest 0.86.0',version_verified_at='2026-09-29',supports_mcp=0,website_url='https://aider.chat/docs/',interfaces='CLI,web GUI',headless_support='YES',ssh_remote_support='YES',openrouter_support='YES',custom_openai_compatible='YES',local_model_support='YES',login_requirement='Provider API key; Copilot token workaround' WHERE name='Aider';
UPDATE harnesses SET current_version='IDE 2.0.0; CLI 1.5.47',version_verified_at='2026-09-29',supports_mcp=1,website_url='https://docs.continue.dev/',interfaces='IDE,CLI,TUI',headless_support='YES',ssh_remote_support='YES',openrouter_support='YES',custom_openai_compatible='YES',local_model_support='YES',login_requirement='API key or Continue account' WHERE name='Continue';
UPDATE harnesses SET current_version='3.14.3',version_verified_at='2026-09-29',supports_mcp=1,website_url='https://zcode.z.ai/en/docs/',interfaces='desktop,IDE',headless_support='NO',ssh_remote_support='YES',openrouter_support='YES',custom_openai_compatible='YES',local_model_support='YES',login_requirement='Z.ai Coding Plan login or provider API key' WHERE name='ZCode';
UPDATE harnesses SET current_version='0.20.0 installed; upstream 0.21.5',version_verified_at='2026-09-29' WHERE name='Hermes Agent';
UPDATE harnesses SET current_version='1.21.0',version_verified_at='2026-09-29',supports_mcp=1,website_url='https://zed.dev/docs/ai/overview',interfaces='IDE,ACP,terminal agents',headless_support='NO',ssh_remote_support='YES',openrouter_support='YES',custom_openai_compatible='YES',local_model_support='YES',login_requirement='API key, Zed plan, ChatGPT login, or Copilot' WHERE name='Zed';

-- A compact, source-backed profile per harness. Each material field remains a
-- separate claim so unknown/partial states are not collapsed into a generic
-- compatibility flag.
WITH profiles(harness,source,builtins,openrouter,openai_compat,anthropic_compat,local_models,subscription_login,custom_endpoint,mcp,mcp_transports,form_factor,headless,ssh_remote) AS (VALUES
 ('Codex CLI','Codex CLI official docs','OpenAI, Bedrock/Mantle, Bedrock Runtime, Ollama, LM Studio','YES','PARTIAL — Responses API only','NO','YES','YES — ChatGPT/Codex','YES — Responses base URL','YES','stdio, Streamable HTTP','CLI/TUI, desktop, IDE, SDK','YES','YES'),
 ('Claude Code','Claude Code official docs','Anthropic, Bedrock, Vertex/Google Cloud Agent Platform, Microsoft Foundry','YES — OpenRouter Anthropic endpoint; Claude routes guaranteed','NO','YES — Anthropic protocol gateways; non-Claude models unsupported','PARTIAL — compatible gateway only','YES — Claude.ai','YES — Anthropic-format gateway','YES','stdio, Streamable HTTP, legacy SSE, WebSocket','CLI/TUI, IDE, SDK, web remote control','YES','YES'),
 ('OpenCode','OpenCode official docs','75+ providers including OpenAI, Anthropic, OpenRouter, Z.ai, Ollama, Azure, Bedrock, Google and xAI','YES','YES — Chat Completions or Responses','YES','YES','YES — ChatGPT, Copilot, GitLab Duo, OpenCode and Z.ai plans','YES','YES','stdio, Streamable HTTP','CLI/TUI, desktop, web, IDE, ACP','YES','YES'),
 ('Pi','Pi official repository docs','OpenAI, Anthropic, OpenRouter, Z.ai, Qwen, Gemini, Bedrock, Azure, DeepSeek, local and coding-plan providers','YES','YES — Chat Completions and Responses','YES','YES','YES — Anthropic, ChatGPT, Codex, Copilot, OpenRouter OAuth','YES','YES','stdio, Streamable HTTP; legacy SSE rejected','CLI/TUI, print, JSON, RPC, SDK','YES','YES'),
 ('Qwen Code','Qwen Code official docs','OpenAI, Anthropic, Gemini, Vertex plus Alibaba, DeepSeek, xAI, MiniMax, Z.ai, Kimi, OpenRouter and others','YES','YES — Chat Completions or Responses','YES','YES','YES — Alibaba Coding/Token plans; former free Qwen OAuth ended','YES','YES','stdio, SSE, Streamable HTTP','CLI/TUI, ACP, HTTP service, web shell, IDE, desktop','YES','YES'),
 ('Gemini CLI','Gemini CLI official docs','Gemini Developer API, Vertex AI, enterprise Gemini Code Assist','NO','NO','NO','PARTIAL — experimental Gemma/LiteRT-LM only','PARTIAL — enterprise Code Assist; consumer subscription access ended','YES — Gemini/Vertex protocol base URLs only','YES','stdio, SSE, Streamable HTTP','CLI/TUI','YES','YES — browser OAuth caveat'),
 ('Goose','Goose official docs','15+ including Anthropic, OpenAI, Google, Ollama, OpenRouter, Azure, Bedrock, Vertex, Groq, Mistral and xAI','YES','YES','YES','YES','YES — ACP subscription providers, Copilot and Cursor','YES','YES','stdio, Streamable HTTP; legacy SSE deprecated','CLI, desktop, API, ACP','YES','YES — remote goosed supported'),
 ('Cline','Cline official docs','Large catalog including Cline, Anthropic, OpenAI/Codex, OpenRouter, Gemini, Bedrock, Azure, DeepSeek, Qwen, Ollama and LM Studio','YES','YES','PARTIAL — Anthropic custom base URL, no generic guarantee','YES','YES — Claude Code, ChatGPT/Codex, Copilot, ClinePass','YES','YES','stdio, Streamable HTTP, legacy SSE','IDE, CLI/TUI, desktop, SDK','YES','YES — dedicated desktop SSH'),
 ('Roo Code','Roo Code archived docs','Anthropic, ChatGPT, Bedrock, DeepSeek, Gemini, local, OpenAI, OpenRouter, Qwen Code CLI, Z.ai and others; frozen','YES','YES','PARTIAL — Anthropic custom base URL only','YES','YES — ChatGPT OAuth; frozen','YES','YES — frozen','stdio, Streamable HTTP, legacy SSE','IDE, CLI/TUI','YES','YES — no dedicated control plane'),
 ('Aider','Aider official docs','OpenAI, Anthropic, Gemini, Groq, DeepSeek, Ollama, OpenRouter, Copilot, Bedrock and LiteLLM providers','YES','YES','NO — no generic route documented','YES','NO — Copilot token workaround only','YES — OpenAI-compatible','NO','none','CLI, optional web GUI','YES','YES — run in remote shell'),
 ('Continue','Continue official docs','Anthropic, OpenAI, Gemini, Ollama, Bedrock, Azure, DeepSeek, OpenRouter, local and many others','YES','YES','PARTIAL — native Anthropic, generic endpoint not established','YES','NO — Continue login is not model-subscription passthrough','YES','YES','stdio, SSE, Streamable HTTP','IDE, CLI/TUI','YES','YES — normal remote CLI'),
 ('ZCode','ZCode official docs','Z.ai plus Anthropic, OpenAI, OpenRouter, Kimi, MiniMax, MiMo and DeepSeek examples','YES','YES','YES','YES — compatible local endpoint','YES — Z.ai Coding Plan','YES','YES','stdio, HTTP, SSE','desktop/IDE','NO','YES — SSH/WSL/container remote development'),
 ('Zed','Zed official docs','Anthropic, OpenAI, Google, Mistral, DeepSeek, xAI, OpenCode, OpenRouter, Bedrock and local providers','YES','YES','YES','YES','YES — Zed plan, ChatGPT, Copilot','YES','YES','stdio, Streamable HTTP with OAuth','IDE, ACP, terminal agents','NO','YES — headless Zed server over SSH')
)
INSERT INTO harness_claims(harness_id,claim_key,claim_value,note,source_id,verified_at)
SELECT h.id,k.key,
 CASE k.key WHEN 'built_in_providers' THEN p.builtins WHEN 'openrouter_support' THEN p.openrouter
  WHEN 'openai_compatible' THEN p.openai_compat WHEN 'anthropic_compatible' THEN p.anthropic_compat
  WHEN 'local_model_support' THEN p.local_models WHEN 'subscription_login' THEN p.subscription_login
  WHEN 'custom_endpoint' THEN p.custom_endpoint WHEN 'mcp_support' THEN p.mcp
  WHEN 'mcp_transports' THEN p.mcp_transports WHEN 'form_factor' THEN p.form_factor
  WHEN 'headless' THEN p.headless WHEN 'ssh_remote' THEN p.ssh_remote END,
 NULL,s.id,'2026-09-29'
FROM profiles p JOIN harnesses h ON h.name=p.harness JOIN sources s ON s.name=p.source
CROSS JOIN (SELECT 'built_in_providers' key UNION ALL SELECT 'openrouter_support' UNION ALL SELECT 'openai_compatible' UNION ALL SELECT 'anthropic_compatible' UNION ALL SELECT 'local_model_support' UNION ALL SELECT 'subscription_login' UNION ALL SELECT 'custom_endpoint' UNION ALL SELECT 'mcp_support' UNION ALL SELECT 'mcp_transports' UNION ALL SELECT 'form_factor' UNION ALL SELECT 'headless' UNION ALL SELECT 'ssh_remote') k;

WITH m(harness,transport,state,note,source) AS (VALUES
 ('Codex CLI','STDIO','YES','Local process transport','Codex CLI official docs'),('Codex CLI','STREAMABLE_HTTP','YES','Bearer and OAuth supported','Codex CLI official docs'),
 ('Claude Code','STDIO','YES',NULL,'Claude Code official docs'),('Claude Code','STREAMABLE_HTTP','YES',NULL,'Claude Code official docs'),('Claude Code','SSE','YES','Legacy/deprecated; WebSocket is also documented and recorded in the transport claim.','Claude Code official docs'),
 ('OpenCode','STDIO','YES',NULL,'OpenCode official docs'),('OpenCode','STREAMABLE_HTTP','YES','OAuth/PKCE supported','OpenCode official docs'),
 ('Pi','STDIO','YES',NULL,'Pi official repository docs'),('Pi','STREAMABLE_HTTP','YES','OAuth/DCR supported','Pi official repository docs'),('Pi','SSE','NO','Legacy SSE explicitly rejected','Pi official repository docs'),
 ('Qwen Code','STDIO','YES',NULL,'Qwen Code official docs'),('Qwen Code','STREAMABLE_HTTP','YES',NULL,'Qwen Code official docs'),('Qwen Code','SSE','YES',NULL,'Qwen Code official docs'),
 ('Gemini CLI','STDIO','YES',NULL,'Gemini CLI official docs'),('Gemini CLI','STREAMABLE_HTTP','YES',NULL,'Gemini CLI official docs'),('Gemini CLI','SSE','YES',NULL,'Gemini CLI official docs'),
 ('Goose','STDIO','YES',NULL,'Goose official docs'),('Goose','STREAMABLE_HTTP','YES',NULL,'Goose official docs'),('Goose','SSE','UNKNOWN','Legacy configuration is deprecated; not treated as active support','Goose official docs'),
 ('Cline','STDIO','YES',NULL,'Cline official docs'),('Cline','STREAMABLE_HTTP','YES','Recommended remote transport','Cline official docs'),('Cline','SSE','YES','Legacy transport','Cline official docs'),
 ('Roo Code','STDIO','YES','Frozen archived support','Roo Code archived docs'),('Roo Code','STREAMABLE_HTTP','YES','Frozen archived support','Roo Code archived docs'),('Roo Code','SSE','YES','Legacy frozen support','Roo Code archived docs'),
 ('Continue','STDIO','YES',NULL,'Continue official docs'),('Continue','STREAMABLE_HTTP','YES',NULL,'Continue official docs'),('Continue','SSE','YES',NULL,'Continue official docs'),
 ('ZCode','STDIO','YES',NULL,'ZCode official docs'),('ZCode','STREAMABLE_HTTP','YES',NULL,'ZCode official docs'),('ZCode','SSE','YES',NULL,'ZCode official docs'),
 ('Zed','STDIO','YES',NULL,'Zed official docs'),('Zed','STREAMABLE_HTTP','YES','Headers or standard MCP OAuth','Zed official docs')
)
INSERT OR REPLACE INTO harness_mcp_capabilities(harness_id,transport,state,note,source_id)
SELECT h.id,m.transport,m.state,m.note,s.id FROM m JOIN harnesses h ON h.name=m.harness JOIN sources s ON s.name=m.source;

WITH a(harness,method,state,note,source) AS (VALUES
 ('Codex CLI','API_KEY','YES','OpenAI or custom provider key','Codex CLI official docs'),('Codex CLI','CHATGPT_CODEX_SUBSCRIPTION','YES','Native ChatGPT sign-in','Codex CLI official docs'),('Codex CLI','OPENROUTER','YES','Custom Responses provider','Codex CLI official docs'),('Codex CLI','LOCAL_ENDPOINT','YES','Ollama/LM Studio or custom Responses endpoint','Codex CLI official docs'),('Codex CLI','CUSTOM_OPENAI_COMPATIBLE','YES','Responses protocol only','Codex CLI official docs'),
 ('Claude Code','API_KEY','YES','Anthropic/cloud credentials','Claude Code official docs'),('Claude Code','NATIVE_PROVIDER_LOGIN','YES','Claude.ai login','Claude Code official docs'),('Claude Code','CODING_SUBSCRIPTION','YES','Claude subscription','Claude Code official docs'),('Claude Code','OPENROUTER','YES','Anthropic-compatible route; Claude models guaranteed','Claude Code official docs'),('Claude Code','CUSTOM_ANTHROPIC_COMPATIBLE','YES','Anthropic-format gateway','Claude Code official docs'),
 ('OpenCode','API_KEY','YES',NULL,'OpenCode official docs'),('OpenCode','OPENROUTER','YES',NULL,'OpenCode official docs'),('OpenCode','CODING_SUBSCRIPTION','YES','Z.ai/OpenCode/GitHub/GitLab plans among supported routes','OpenCode official docs'),('OpenCode','CHATGPT_CODEX_SUBSCRIPTION','YES','ChatGPT Plus/Pro login','OpenCode official docs'),('OpenCode','LOCAL_ENDPOINT','YES',NULL,'OpenCode official docs'),('OpenCode','CUSTOM_OPENAI_COMPATIBLE','YES',NULL,'OpenCode official docs'),('OpenCode','CUSTOM_ANTHROPIC_COMPATIBLE','YES',NULL,'OpenCode official docs'),
 ('Pi','API_KEY','YES',NULL,'Pi official repository docs'),('Pi','OPENROUTER','YES','API key or OAuth PKCE','Pi official repository docs'),('Pi','CODING_SUBSCRIPTION','YES','Multiple coding plan providers','Pi official repository docs'),('Pi','CHATGPT_CODEX_SUBSCRIPTION','YES','Sign in with ChatGPT / Codex','Pi official repository docs'),('Pi','LOCAL_ENDPOINT','YES',NULL,'Pi official repository docs'),('Pi','CUSTOM_OPENAI_COMPATIBLE','YES',NULL,'Pi official repository docs'),('Pi','CUSTOM_ANTHROPIC_COMPATIBLE','YES',NULL,'Pi official repository docs'),
 ('Qwen Code','API_KEY','YES',NULL,'Qwen Code official docs'),('Qwen Code','OPENROUTER','YES',NULL,'Qwen Code official docs'),('Qwen Code','CODING_SUBSCRIPTION','YES','Alibaba plans','Qwen Code official docs'),('Qwen Code','LOCAL_ENDPOINT','YES',NULL,'Qwen Code official docs'),('Qwen Code','CUSTOM_OPENAI_COMPATIBLE','YES',NULL,'Qwen Code official docs'),('Qwen Code','CUSTOM_ANTHROPIC_COMPATIBLE','YES',NULL,'Qwen Code official docs'),
 ('Gemini CLI','API_KEY','YES',NULL,'Gemini CLI official docs'),('Gemini CLI','NATIVE_PROVIDER_LOGIN','YES','Enterprise Code Assist; consumer subscription access ended','Gemini CLI official docs'),('Gemini CLI','LOCAL_ENDPOINT','UNKNOWN','Experimental Gemma path only','Gemini CLI official docs'),
 ('Goose','API_KEY','YES',NULL,'Goose official docs'),('Goose','OPENROUTER','YES',NULL,'Goose official docs'),('Goose','CODING_SUBSCRIPTION','YES','ACP subscription providers','Goose official docs'),('Goose','LOCAL_ENDPOINT','YES',NULL,'Goose official docs'),('Goose','CUSTOM_OPENAI_COMPATIBLE','YES',NULL,'Goose official docs'),('Goose','CUSTOM_ANTHROPIC_COMPATIBLE','YES',NULL,'Goose official docs'),
 ('Cline','API_KEY','YES',NULL,'Cline official docs'),('Cline','OPENROUTER','YES',NULL,'Cline official docs'),('Cline','CODING_SUBSCRIPTION','YES','Claude Code/Copilot/ClinePass','Cline official docs'),('Cline','CHATGPT_CODEX_SUBSCRIPTION','YES','OpenAI Codex OAuth','Cline official docs'),('Cline','LOCAL_ENDPOINT','YES',NULL,'Cline official docs'),('Cline','CUSTOM_OPENAI_COMPATIBLE','YES',NULL,'Cline official docs'),('Cline','CUSTOM_ANTHROPIC_COMPATIBLE','UNKNOWN','Custom base URL without generic guarantee','Cline official docs'),
 ('Roo Code','API_KEY','YES','Frozen','Roo Code archived docs'),('Roo Code','OPENROUTER','YES','Frozen','Roo Code archived docs'),('Roo Code','CHATGPT_CODEX_SUBSCRIPTION','YES','Frozen ChatGPT OAuth','Roo Code archived docs'),('Roo Code','LOCAL_ENDPOINT','YES','Frozen','Roo Code archived docs'),('Roo Code','CUSTOM_OPENAI_COMPATIBLE','YES','Frozen','Roo Code archived docs'),
 ('Aider','API_KEY','YES',NULL,'Aider official docs'),('Aider','OPENROUTER','YES',NULL,'Aider official docs'),('Aider','LOCAL_ENDPOINT','YES',NULL,'Aider official docs'),('Aider','CUSTOM_OPENAI_COMPATIBLE','YES',NULL,'Aider official docs'),('Aider','CODING_SUBSCRIPTION','UNKNOWN','Copilot token workaround; no native subscription OAuth','Aider official docs'),
 ('Continue','API_KEY','YES',NULL,'Continue official docs'),('Continue','OPENROUTER','YES',NULL,'Continue official docs'),('Continue','LOCAL_ENDPOINT','YES',NULL,'Continue official docs'),('Continue','CUSTOM_OPENAI_COMPATIBLE','YES',NULL,'Continue official docs'),('Continue','CODING_SUBSCRIPTION','NO','Continue account is not provider subscription passthrough','Continue official docs'),
 ('ZCode','API_KEY','YES',NULL,'ZCode official docs'),('ZCode','OPENROUTER','YES',NULL,'ZCode official docs'),('ZCode','CODING_SUBSCRIPTION','YES','Z.ai Coding Plan','ZCode official docs'),('ZCode','LOCAL_ENDPOINT','YES','Compatible endpoint','ZCode official docs'),('ZCode','CUSTOM_OPENAI_COMPATIBLE','YES',NULL,'ZCode official docs'),('ZCode','CUSTOM_ANTHROPIC_COMPATIBLE','YES',NULL,'ZCode official docs'),
 ('Zed','API_KEY','YES',NULL,'Zed official docs'),('Zed','OPENROUTER','YES',NULL,'Zed official docs'),('Zed','CHATGPT_CODEX_SUBSCRIPTION','YES','ChatGPT Plus/Pro sign-in','Zed official docs'),('Zed','CODING_SUBSCRIPTION','YES','Zed plan or Copilot','Zed official docs'),('Zed','LOCAL_ENDPOINT','YES',NULL,'Zed official docs'),('Zed','CUSTOM_OPENAI_COMPATIBLE','YES',NULL,'Zed official docs'),('Zed','CUSTOM_ANTHROPIC_COMPATIBLE','YES',NULL,'Zed official docs')
)
INSERT OR REPLACE INTO harness_access_methods(harness_id,access_method,state,note,source_id,verified_at)
SELECT h.id,a.method,a.state,a.note,s.id,'2026-09-29' FROM a JOIN harnesses h ON h.name=a.harness JOIN sources s ON s.name=a.source;

-- Explicitly verified user-requested route cases. Provider tool support comes
-- from the exact offering record; reliability stays UNVERIFIED unless a
-- credible route-specific test exists.
INSERT OR REPLACE INTO route_compatibility_evidence(harness_id,offering_id,capability,access_method,harness_can_use_model,harness_supports_mcp,provider_tool_calls,tool_reliability,mcp_workflow_status,reason,source_id,verified_at)
SELECT h.id,o.id,'MCP_TOOLS','custom OpenAI-compatible endpoint','YES','YES',o.tool_support,'UNVERIFIED','COMPATIBLE_WITH_CONFIGURATION','OpenCode can address the Z.ai Coding Plan/OpenAI-compatible endpoint and host MCP; this exact route advertises tools. Endpoint and model IDs must be configured.',COALESCE(h.source_id,o.source_id),'2026-09-29'
FROM harnesses h,provider_offerings o JOIN providers p ON p.id=o.provider_id
WHERE h.name='OpenCode' AND p.name='Z.ai' AND o.api_model_id='glm-5.3';

INSERT OR REPLACE INTO route_compatibility_evidence(harness_id,offering_id,capability,access_method,harness_can_use_model,harness_supports_mcp,provider_tool_calls,tool_reliability,mcp_workflow_status,reason,source_id,verified_at)
SELECT h.id,o.id,'MCP_TOOLS','OpenRouter API key','YES','YES',o.tool_support,'UNVERIFIED','COMPATIBLE_WITH_CONFIGURATION','OpenCode has an OpenRouter provider path and MCP hosting; the exact GLM route advertises tools. No independent tool-reliability run is recorded.',COALESCE(h.source_id,o.source_id),'2026-09-29'
FROM harnesses h,provider_offerings o JOIN providers p ON p.id=o.provider_id
WHERE h.name='OpenCode' AND p.name='OpenRouter' AND o.api_model_id='z-ai/glm-5.3';

INSERT OR REPLACE INTO route_compatibility_evidence(harness_id,offering_id,capability,access_method,harness_can_use_model,harness_supports_mcp,provider_tool_calls,tool_reliability,mcp_workflow_status,reason,source_id,verified_at)
SELECT h.id,o.id,'MCP_TOOLS','OpenRouter API key','YES','YES',o.tool_support,'UNVERIFIED','COMPATIBLE_WITH_CONFIGURATION','Pi supports OpenRouter/custom providers and MCP extensions; the exact GLM route advertises tools. Configure both provider and MCP server.',COALESCE(h.source_id,o.source_id),'2026-09-29'
FROM harnesses h,provider_offerings o JOIN providers p ON p.id=o.provider_id
WHERE h.name='Pi' AND p.name='OpenRouter' AND o.api_model_id='z-ai/glm-5.3';

INSERT OR REPLACE INTO route_compatibility_evidence(harness_id,offering_id,capability,access_method,harness_can_use_model,harness_supports_mcp,provider_tool_calls,tool_reliability,mcp_workflow_status,reason,source_id,verified_at)
SELECT h.id,o.id,'MCP_TOOLS','OpenRouter API key','YES','YES',o.tool_support,'UNVERIFIED','COMPATIBLE_WITH_CONFIGURATION','Hermes 0.20.0 includes OpenRouter and stdio/HTTP/SSE MCP clients; this exact GLM route advertises tools. No independent reliability result is recorded.',(SELECT id FROM sources WHERE name='Hermes installed version inspection'),'2026-09-29'
FROM harnesses h,provider_offerings o JOIN providers p ON p.id=o.provider_id
WHERE h.name='Hermes Agent' AND p.name='OpenRouter' AND o.api_model_id='z-ai/glm-5.3';

INSERT OR REPLACE INTO route_compatibility_evidence(harness_id,offering_id,capability,access_method,harness_can_use_model,harness_supports_mcp,provider_tool_calls,tool_reliability,mcp_workflow_status,reason,source_id,verified_at)
SELECT h.id,o.id,'MCP_TOOLS','OpenRouter API key','YES','YES',o.tool_support,'UNVERIFIED','COMPATIBLE_WITH_CONFIGURATION','Hermes 0.20.0 includes OpenRouter and MCP clients; this exact DeepSeek V4 Pro route advertises tools. No independent tool-reliability run is recorded.',(SELECT id FROM sources WHERE name='Hermes installed version inspection'),'2026-09-29'
FROM harnesses h,provider_offerings o JOIN providers p ON p.id=o.provider_id
WHERE h.name='Hermes Agent' AND p.name='OpenRouter' AND o.api_model_id='deepseek/deepseek-v4-pro';

INSERT OR REPLACE INTO route_compatibility_evidence(harness_id,offering_id,capability,access_method,harness_can_use_model,harness_supports_mcp,provider_tool_calls,tool_reliability,mcp_workflow_status,reason,source_id,verified_at)
SELECT h.id,o.id,'MCP_TOOLS','DeepSeek API key','YES','YES',o.tool_support,'UNVERIFIED','COMPATIBLE','Hermes 0.20.0 includes a native DeepSeek provider and MCP clients; this exact direct route advertises tools. No independent tool-reliability run is recorded.',(SELECT id FROM sources WHERE name='Hermes installed version inspection'),'2026-09-29'
FROM harnesses h,provider_offerings o JOIN providers p ON p.id=o.provider_id
WHERE h.name='Hermes Agent' AND p.name='DeepSeek' AND o.api_model_id='deepseek-v4-pro';

INSERT OR REPLACE INTO route_compatibility_evidence(harness_id,offering_id,capability,access_method,harness_can_use_model,harness_supports_mcp,provider_tool_calls,tool_reliability,mcp_workflow_status,reason,source_id,verified_at)
SELECT h.id,o.id,'MCP_TOOLS','OpenRouter API key','YES','YES',o.tool_support,'UNVERIFIED','COMPATIBLE_WITH_CONFIGURATION','Hermes can call OpenRouter and host MCP. This $0 router filters for requested capabilities, but the underlying free model/provider can change, so route reliability is unverified.',(SELECT id FROM sources WHERE name='Hermes installed version inspection'),'2026-09-29'
FROM harnesses h,provider_offerings o JOIN providers p ON p.id=o.provider_id
WHERE h.name='Hermes Agent' AND p.name='OpenRouter' AND o.api_model_id='openrouter/free';

INSERT OR REPLACE INTO route_compatibility_evidence(harness_id,offering_id,capability,access_method,harness_can_use_model,harness_supports_mcp,provider_tool_calls,tool_reliability,mcp_workflow_status,reason,source_id,verified_at)
SELECT h.id,o.id,'TOOLS','OpenAI API key or ChatGPT/Codex subscription','YES','YES',o.tool_support,'RELIABLE','COMPATIBLE','Codex CLI natively supports OpenAI models and tool use. Subscription login and API-key access are distinct access methods.',COALESCE(h.source_id,o.source_id),'2026-09-29'
FROM harnesses h,provider_offerings o JOIN providers p ON p.id=o.provider_id
WHERE h.name='Codex CLI' AND p.name='OpenAI' AND o.api_model_id='gpt-6.1-sol';

-- MCP workflow hosts: transport overlap is the gating fact; the selected
-- route is evaluated independently by route_compatibility_evidence/domain.py.
INSERT OR REPLACE INTO workflow_harness_compatibility(integration_id,harness_id,state,reason,source_id,verified_at)
SELECT wi.id,h.id,'CONFIGURATION','The harness supports local stdio MCP servers. Install the Unreal plugin/server and point the harness at its command.',wi.source_id,'2026-09-29'
FROM workflow_integrations wi JOIN workflows w ON w.id=wi.workflow_id CROSS JOIN harnesses h
WHERE w.slug='unreal-engine' AND h.supports_mcp=1;

INSERT OR REPLACE INTO workflow_harness_compatibility(integration_id,harness_id,state,reason,source_id,verified_at)
SELECT wi.id,h.id,'CONFIGURATION','The harness supports local stdio MCP servers; the exact REAPER bridge and its prerequisites must be installed.',wi.source_id,'2026-09-29'
FROM workflow_integrations wi JOIN workflows w ON w.id=wi.workflow_id CROSS JOIN harnesses h
WHERE w.slug='reaper' AND h.supports_mcp=1;

INSERT OR REPLACE INTO workflow_harness_compatibility(integration_id,harness_id,state,reason,source_id,verified_at)
SELECT wi.id,h.id,'CONFIGURATION','The harness supports an MCP transport offered by this integration; install/configure the exact server and its authentication or local prerequisites.',wi.source_id,'2026-09-29'
FROM workflow_integrations wi JOIN workflows w ON w.id=wi.workflow_id CROSS JOIN harnesses h
WHERE w.slug NOT IN ('unreal-engine','reaper') AND h.supports_mcp=1;
