INSERT OR IGNORE INTO sources (name, url, source_type, reliability) VALUES
 ('Models.dev catalog', 'https://models.dev/api.json', 'machine-readable catalog', 'MEDIUM'),
 ('OpenRouter model API', 'https://openrouter.ai/api/v1/models', 'machine-readable catalog', 'MEDIUM'),
 ('LiteLLM price map', 'https://github.com/BerriAI/litellm/blob/main/model_prices_and_context_window.json', 'cross-check', 'MEDIUM'),
 ('Hermes MCP documentation', 'https://github.com/hermes-agent-org/hermes/blob/main/website/docs/user-guide/features/mcp.md', 'documentation', 'HIGH'),
 ('LiveBench', 'https://livebench.ai/', 'benchmark', 'HIGH'),
 ('SWE-bench', 'https://www.swebench.com/', 'benchmark', 'HIGH'),
 ('Terminal-Bench', 'https://www.tbench.ai/', 'benchmark', 'HIGH');
INSERT OR IGNORE INTO sources (name, url, source_type, reliability) VALUES
 ('Artificial Analysis Intelligence Index', 'https://artificialanalysis.ai/evaluations/artificial-analysis-intelligence-index', 'benchmark', 'HIGH');

INSERT OR IGNORE INTO labs (name, website_url, source_id) VALUES
 ('Z.ai', 'https://z.ai/', 1), ('OpenAI', 'https://openai.com/', 1),
 ('Alibaba Qwen', 'https://qwen.ai/', 1), ('DeepSeek', 'https://www.deepseek.com/', 1),
 ('Google', 'https://ai.google/', 1), ('Moonshot AI', 'https://moonshot.ai/', 1),
 ('MiniMax', 'https://www.minimaxi.com/', 1);

INSERT OR IGNORE INTO providers (name, website_url) VALUES
 ('Z.ai', 'https://z.ai/'), ('OpenRouter', 'https://openrouter.ai/'),
 ('DeepInfra', 'https://deepinfra.com/'), ('Groq', 'https://groq.com/'),
 ('Cerebras', 'https://cerebras.ai/'), ('Moonshot AI', 'https://moonshot.ai/'),
 ('OpenAI', 'https://openai.com/'), ('Google AI', 'https://ai.google/'),
 ('Alibaba Cloud', 'https://www.alibabacloud.com/'), ('Ollama', 'https://ollama.com/');

INSERT OR IGNORE INTO models (canonical_name, vendor, modality, open_weights, lab_id, canonical_slug) VALUES
 ('GLM-5.3', 'Z.ai', 'text', 1, 1, 'zhipuai/glm-5.3'),
 ('GPT-OSS 120B', 'OpenAI', 'text', 1, 2, 'openai/gpt-oss-120b'),
 ('Qwen3 Coder 480B A35B Instruct', 'Alibaba Qwen', 'text', 1, 3, 'alibaba/qwen3-coder-480b-a35b-instruct'),
 ('DeepSeek V3 0324', 'DeepSeek', 'text', 1, 4, 'deepseek/deepseek-v3-0324'),
 ('Gemma 4 31B IT', 'Google', 'text', 1, 5, 'google/gemma-4-31b-it'),
 ('Kimi K3', 'Moonshot AI', 'text', 1, 6, 'moonshotai/kimi-k3'),
 ('MiniMax M3', 'MiniMax', 'text', 1, 7, 'minimax/minimax-m3');

INSERT OR IGNORE INTO model_aliases (model_id, alias, provider_id, source_id)
SELECT m.id, 'glm-5.3', p.id, 1 FROM models m, providers p WHERE m.canonical_slug='zhipuai/glm-5.3' AND p.name='Z.ai';
INSERT OR IGNORE INTO model_aliases (model_id, alias, provider_id, source_id)
SELECT m.id, 'z-ai/glm-5.3', p.id, 1 FROM models m, providers p WHERE m.canonical_slug='zhipuai/glm-5.3' AND p.name='OpenRouter';

INSERT OR IGNORE INTO provider_offerings (model_id, provider_id, api_model_id, context_limit, max_output_tokens, tool_support, free_status, source_id) VALUES
 ((SELECT id FROM models WHERE canonical_slug='zhipuai/glm-5.3'), (SELECT id FROM providers WHERE name='Z.ai'), 'glm-5.3', 1000000, 131072, 'YES', 'PAID', 1),
 ((SELECT id FROM models WHERE canonical_slug='zhipuai/glm-5.3'), (SELECT id FROM providers WHERE name='OpenRouter'), 'z-ai/glm-5.3', 1000000, 131072, 'YES', 'UNKNOWN', 2),
 ((SELECT id FROM models WHERE canonical_slug='openai/gpt-oss-120b'), (SELECT id FROM providers WHERE name='Groq'), 'openai/gpt-oss-120b', 131072, 65536, 'YES', 'PAID', 1),
 ((SELECT id FROM models WHERE canonical_slug='openai/gpt-oss-120b'), (SELECT id FROM providers WHERE name='Cerebras'), 'gpt-oss-120b', 131072, 40960, 'YES', 'PAID', 1),
 ((SELECT id FROM models WHERE canonical_slug='alibaba/qwen3-coder-480b-a35b-instruct'), (SELECT id FROM providers WHERE name='DeepInfra'), 'Qwen/Qwen3-Coder-480B-A35B-Instruct-Turbo', 262144, 66536, 'YES', 'PAID', 1),
 ((SELECT id FROM models WHERE canonical_slug='deepseek/deepseek-v3-0324'), (SELECT id FROM providers WHERE name='DeepInfra'), 'deepseek-ai/DeepSeek-V3-0324', 163840, 163840, 'YES', 'PAID', 1),
 ((SELECT id FROM models WHERE canonical_slug='google/gemma-4-31b-it'), (SELECT id FROM providers WHERE name='DeepInfra'), 'google/gemma-4-31B-it', 262144, 32768, 'YES', 'PAID', 1),
 ((SELECT id FROM models WHERE canonical_slug='moonshotai/kimi-k3'), (SELECT id FROM providers WHERE name='Moonshot AI'), 'kimi-k3', 1048576, 1048576, 'YES', 'PAID', 1),
 ((SELECT id FROM models WHERE canonical_slug='minimax/minimax-m3'), (SELECT id FROM providers WHERE name='DeepInfra'), 'MiniMaxAI/MiniMax-M3', 524288, 512000, 'YES', 'PAID', 1);

INSERT INTO pricing_records (offering_id, price_type, amount, source_id)
SELECT id, 'INPUT', 1.4, 1 FROM provider_offerings WHERE api_model_id='glm-5.3' AND provider_id=(SELECT id FROM providers WHERE name='Z.ai');
INSERT INTO pricing_records (offering_id, price_type, amount, source_id)
SELECT id, 'OUTPUT', 4.4, 1 FROM provider_offerings WHERE api_model_id='glm-5.3' AND provider_id=(SELECT id FROM providers WHERE name='Z.ai');
INSERT INTO pricing_records (offering_id, price_type, amount, source_id)
SELECT id, 'CACHE_READ', 0.26, 1 FROM provider_offerings WHERE api_model_id='glm-5.3' AND provider_id=(SELECT id FROM providers WHERE name='Z.ai');
INSERT INTO pricing_records (offering_id, price_type, amount, source_id)
SELECT id, 'INPUT', 0.15, 1 FROM provider_offerings WHERE api_model_id='openai/gpt-oss-120b' AND provider_id=(SELECT id FROM providers WHERE name='Groq');
INSERT INTO pricing_records (offering_id, price_type, amount, source_id)
SELECT id, 'OUTPUT', 0.6, 1 FROM provider_offerings WHERE api_model_id='openai/gpt-oss-120b' AND provider_id=(SELECT id FROM providers WHERE name='Groq');

INSERT OR IGNORE INTO use_cases (slug, name, description) VALUES
 ('general','General','General purpose work'), ('reasoning','Reasoning','Multi-step analysis'), ('coding','Coding','Software development'),
 ('agentic-coding','Agentic Coding','Autonomous repository work'), ('tool-calling','Tool Calling','Structured tool use'),
 ('long-horizon-agents','Long-Horizon Agents','Extended agent tasks'), ('long-context','Long Context','Large-context work'),
 ('vision','Vision','Image and document understanding'), ('image','Image','Image generation or editing'), ('video','Video','Video understanding or generation'),
 ('audio','Audio','Audio understanding or generation'), ('3d','3D','Three-dimensional content'), ('low-latency','Low Latency','Fast responses'),
 ('cheapest','Cheapest','Cost-sensitive work'), ('open-weight','Open Weight','Redistributable weights'), ('local-self-hosted','Local/Self Hosted','On-premise deployment'),
 ('multilingual','Multilingual','Multiple-language work'), ('data-analysis','Data Analysis','Structured analysis');

INSERT OR IGNORE INTO harnesses (name, organization, open_source, license, interfaces, supported_os, headless_support, ssh_remote_support, openrouter_support, custom_openai_compatible, local_model_support, login_requirement, skills_plugins, subagents, browser_support, computer_use_support, source_id) VALUES
 ('Codex CLI','OpenAI','NO',NULL,'CLI','macOS,Linux,Windows','YES','YES','UNKNOWN','YES','UNKNOWN','Login or API key','YES','YES','YES','YES',NULL),
 ('Claude Code','Anthropic','NO',NULL,'CLI','macOS,Linux,Windows','YES','YES','NO','NO','NO','Anthropic login or API key','YES','YES','YES','YES',NULL),
 ('OpenCode','Anomaly','YES','MIT','CLI,TUI,desktop','macOS,Linux,Windows','YES','YES','YES','YES','YES','Provider API key','YES','YES','YES','UNKNOWN',1),
 ('Pi','Mario Zechner','YES','MIT','CLI','macOS,Linux,Windows','YES','YES','YES','YES','YES','Provider API key','YES','YES','UNKNOWN','UNKNOWN',NULL),
 ('Qwen Code','Alibaba','UNKNOWN',NULL,'CLI','macOS,Linux,Windows','YES','YES','UNKNOWN','UNKNOWN','UNKNOWN','UNKNOWN','YES','UNKNOWN','UNKNOWN','UNKNOWN',NULL),
 ('Gemini CLI','Google','YES','Apache-2.0','CLI','macOS,Linux,Windows','YES','YES','UNKNOWN','UNKNOWN','UNKNOWN','Google login or API key','YES','YES','YES','UNKNOWN',NULL),
 ('Goose','Block','YES','Apache-2.0','CLI,desktop','macOS,Linux,Windows','YES','YES','YES','YES','YES','Provider API key','YES','YES','YES','YES',NULL),
 ('Cline','Cline','YES','Apache-2.0','IDE','macOS,Linux,Windows','NO','UNKNOWN','YES','YES','YES','Provider API key','YES','YES','YES','YES',NULL),
 ('Roo Code','Roo Code','YES','Apache-2.0','IDE','macOS,Linux,Windows','NO','UNKNOWN','YES','YES','YES','Provider API key','YES','YES','YES','YES',NULL),
 ('Aider','Aider','YES','Apache-2.0','CLI','macOS,Linux,Windows','YES','YES','YES','YES','YES','Provider API key','NO','NO','NO','NO',NULL),
 ('Continue','Continue','YES','Apache-2.0','IDE,CLI','macOS,Linux,Windows','YES','YES','YES','YES','YES','Provider API key','YES','YES','YES','UNKNOWN',NULL),
 ('ZCode','Z.ai','UNKNOWN',NULL,'CLI,IDE','macOS,Linux,Windows','UNKNOWN','UNKNOWN','UNKNOWN','UNKNOWN','UNKNOWN','UNKNOWN','UNKNOWN','UNKNOWN','UNKNOWN','UNKNOWN',NULL),
 ('Zed','Zed Industries','YES','GPL-3.0','IDE','macOS,Linux','NO','YES','UNKNOWN','YES','YES','UNKNOWN','YES','UNKNOWN','YES','UNKNOWN',NULL),
 ('Hermes Agent','Nous Research','YES','MIT','CLI,API','macOS,Linux,Windows','YES','YES','YES','YES','YES','Provider API key','YES','YES','YES','YES',4);

UPDATE harnesses SET supports_mcp=1 WHERE name IN ('Codex CLI','Claude Code','OpenCode','Pi','Gemini CLI','Goose','Cline','Roo Code','Continue','Hermes Agent');
INSERT OR IGNORE INTO harness_mcp_capabilities (harness_id, transport, state, source_id) SELECT id,'STDIO','YES',source_id FROM harnesses WHERE name='Hermes Agent';
INSERT OR IGNORE INTO harness_mcp_capabilities (harness_id, transport, state, source_id) SELECT id,'STREAMABLE_HTTP','YES',source_id FROM harnesses WHERE name='Hermes Agent';
INSERT OR IGNORE INTO harness_mcp_capabilities (harness_id, transport, state, source_id) SELECT id,'TOOLS','YES',source_id FROM harnesses WHERE name='Hermes Agent';
INSERT OR IGNORE INTO harness_mcp_capabilities (harness_id, transport, state, source_id) SELECT id,'RESOURCES','YES',source_id FROM harnesses WHERE name='Hermes Agent';
INSERT OR IGNORE INTO harness_mcp_capabilities (harness_id, transport, state, source_id) SELECT id,'PROMPTS','YES',source_id FROM harnesses WHERE name='Hermes Agent';

INSERT OR IGNORE INTO harness_provider_compatibility (harness_id, provider_id, support_mode, source_id, note) VALUES
 ((SELECT id FROM harnesses WHERE name='OpenCode'),(SELECT id FROM providers WHERE name='Z.ai'),'OPENAI_COMPATIBLE',1,'Configure the provider endpoint and API key.'),
 ((SELECT id FROM harnesses WHERE name='OpenCode'),(SELECT id FROM providers WHERE name='OpenRouter'),'OPENROUTER',1,'OpenRouter is supported by configuration.'),
 ((SELECT id FROM harnesses WHERE name='Hermes Agent'),(SELECT id FROM providers WHERE name='OpenRouter'),'OPENROUTER',4,'Configured provider route.'),
 ((SELECT id FROM harnesses WHERE name='Aider'),(SELECT id FROM providers WHERE name='OpenRouter'),'OPENROUTER',1,'OpenRouter model IDs are supported by configuration.');

INSERT OR IGNORE INTO benchmarks (name, version, category, source_id) VALUES
 ('LiveBench','2025-02','General/Reasoning/Coding',5), ('SWE-bench Verified','500-instance human-filtered subset','Coding agent',6), ('Terminal-Bench','2.0','Agentic coding',7), ('Artificial Analysis Intelligence Index','4.3.2','General/Reasoning/Coding/Agents',8);
