-- Developer-plan catalog, plan-to-harness evidence, and explicit access routes.
-- Subscription allowances stay as provider-published text unless the provider
-- publishes a genuinely comparable numeric allowance.

ALTER TABLE plans ADD COLUMN plan_type TEXT NOT NULL DEFAULT 'SUBSCRIPTION'
  CHECK (plan_type IN ('SUBSCRIPTION','FREE','PAYG','ENTERPRISE'));
ALTER TABLE plans ADD COLUMN monthly_price NUMERIC;
ALTER TABLE plans ADD COLUMN annual_price NUMERIC;
ALTER TABLE plans ADD COLUMN currency TEXT NOT NULL DEFAULT 'USD';
ALTER TABLE plans ADD COLUMN price_note TEXT;
ALTER TABLE plans ADD COLUMN models_included TEXT;
ALTER TABLE plans ADD COLUMN api_access TEXT NOT NULL DEFAULT 'UNKNOWN'
  CHECK (api_access IN ('YES','NO','LIMITED','UNKNOWN'));
ALTER TABLE plans ADD COLUMN coding_agent_access TEXT NOT NULL DEFAULT 'UNKNOWN'
  CHECK (coding_agent_access IN ('YES','NO','LIMITED','UNKNOWN'));
ALTER TABLE plans ADD COLUMN quota_description TEXT;
ALTER TABLE plans ADD COLUMN reset_interval TEXT;
ALTER TABLE plans ADD COLUMN published_limit TEXT;
ALTER TABLE plans ADD COLUMN fair_use TEXT;
ALTER TABLE plans ADD COLUMN region_restrictions TEXT;
ALTER TABLE plans ADD COLUMN is_coding INTEGER NOT NULL DEFAULT 0 CHECK (is_coding IN (0,1));
ALTER TABLE plans ADD COLUMN status TEXT NOT NULL DEFAULT 'ACTIVE'
  CHECK (status IN ('ACTIVE','LIMITED','WAITLIST','UNKNOWN'));
ALTER TABLE plans ADD COLUMN verified_at TEXT;

CREATE TABLE plan_harness_compatibility (
  id INTEGER PRIMARY KEY,
  plan_id INTEGER NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
  harness_id INTEGER NOT NULL REFERENCES harnesses(id) ON DELETE CASCADE,
  support_level TEXT NOT NULL CHECK (support_level IN (
    'OFFICIAL','DOCUMENTED_THIRD_PARTY','API_ROUTE','PROXY_ADAPTER','UNSUPPORTED','UNKNOWN'
  )),
  note TEXT,
  source_id INTEGER NOT NULL REFERENCES sources(id),
  verified_at TEXT NOT NULL,
  UNIQUE(plan_id,harness_id)
);

CREATE TABLE model_access_routes (
  id INTEGER PRIMARY KEY,
  model_family TEXT NOT NULL,
  provider_id INTEGER REFERENCES providers(id),
  plan_id INTEGER REFERENCES plans(id) ON DELETE CASCADE,
  route_name TEXT NOT NULL,
  route_type TEXT NOT NULL CHECK (route_type IN ('SUBSCRIPTION','DIRECT_API','AGGREGATOR','FREE')),
  billing_basis TEXT NOT NULL,
  access_detail TEXT NOT NULL,
  source_id INTEGER NOT NULL REFERENCES sources(id),
  verified_at TEXT NOT NULL,
  UNIQUE(model_family,route_name)
);

CREATE INDEX idx_plans_filter ON plans(plan_type,is_coding,monthly_price,provider_id);
CREATE INDEX idx_plan_harness_plan ON plan_harness_compatibility(plan_id,harness_id);
CREATE INDEX idx_model_access_family ON model_access_routes(model_family,route_type);

INSERT OR IGNORE INTO sources(name,url,source_type,fetched_at,reliability) VALUES
 ('OpenAI ChatGPT pricing','https://learn.chatgpt.com/docs/pricing','official pricing','2026-09-29','HIGH'),
 ('OpenAI API pricing','https://platform.openai.com/pricing','official pricing','2026-09-29','HIGH'),
 ('Anthropic Claude pricing','https://claude.com/pricing','official pricing','2026-09-29','HIGH'),
 ('Anthropic Claude Code plan guide','https://support.claude.com/en/articles/11145838-use-claude-code-with-your-pro-or-max-plan','official documentation','2026-09-29','HIGH'),
 ('Z.ai Coding Plan overview','https://docs.z.ai/devpack/overview','official documentation','2026-09-29','HIGH'),
 ('Z.ai API pricing','https://docs.z.ai/guides/overview/pricing','official pricing','2026-09-29','HIGH'),
 ('Google Gemini Code Assist pricing','https://cloud.google.com/products/gemini/pricing','official pricing','2026-09-29','HIGH'),
 ('Google Gemini Code Assist quotas','https://docs.cloud.google.com/gemini/docs/quotas','official documentation','2026-09-29','HIGH'),
 ('Google Gemini API pricing','https://ai.google.dev/gemini-api/docs/pricing','official pricing','2026-09-29','HIGH'),
 ('Alibaba Coding Plan','https://www.alibabacloud.com/help/en/model-studio/coding-plan-guide/','official documentation','2026-09-29','HIGH'),
 ('Alibaba Token Plan','https://www.alibabacloud.com/help/en/model-studio/token-plan-overview','official documentation','2026-09-29','HIGH'),
 ('MiniMax Token Plan','https://platform.minimax.io/subscribe/token-plan','official pricing','2026-09-29','HIGH'),
 ('Kimi membership pricing','https://www.kimi.com/en/help/membership/membership-pricing','official pricing','2026-09-29','HIGH'),
 ('Kimi Code membership guide','https://www.kimi.com/en/help/kimi-code/membership-guide','official documentation','2026-09-29','HIGH'),
 ('DeepSeek API pricing','https://api-docs.deepseek.com/quick_start/pricing/','official pricing','2026-09-29','HIGH'),
 ('OpenCode Go','https://dev.opencode.ai/docs/go/','official documentation','2026-09-29','HIGH'),
 ('OpenCode Zen','https://dev.opencode.ai/docs/zen','official pricing','2026-09-29','HIGH'),
 ('OpenCode provider documentation','https://opencode.ai/docs/providers','official documentation','2026-09-29','HIGH');

INSERT OR IGNORE INTO providers(name,website_url) VALUES
 ('Anthropic','https://anthropic.com/'),
 ('Google','https://cloud.google.com/gemini/'),
 ('Alibaba Coding Plan','https://www.alibabacloud.com/help/en/model-studio/coding-plan-guide/'),
 ('Alibaba Token Plan','https://www.alibabacloud.com/help/en/model-studio/token-plan-overview'),
 ('MiniMax Token Plan (minimax.io)','https://platform.minimax.io/subscribe/token-plan'),
 ('MiniMax (minimax.io)','https://platform.minimax.io/'),
 ('Kimi For Coding (kimi.com)','https://www.kimi.com/code'),
 ('DeepSeek','https://www.deepseek.com/'),
 ('OpenCode Go','https://opencode.ai/go'),
 ('OpenCode Zen','https://opencode.ai/zen');

INSERT INTO plans(provider_id,name,description,source_id,plan_type,monthly_price,annual_price,currency,price_note,models_included,api_access,coding_agent_access,quota_description,reset_interval,published_limit,fair_use,region_restrictions,is_coding,status,verified_at) VALUES
 ((SELECT id FROM providers WHERE name='OpenAI'),'ChatGPT Free','Free ChatGPT access with limited Codex availability.',(SELECT id FROM sources WHERE name='OpenAI ChatGPT pricing'),'FREE',0,NULL,'USD',NULL,'GPT-6 Luna; availability may vary','NO','LIMITED','Exact allowance not published','Provider-displayed reset','No exact token or request allowance published','Subject to plan limits and availability.','ChatGPT availability varies by supported country.',1,'ACTIVE','2026-09-29'),
 ((SELECT id FROM providers WHERE name='OpenAI'),'ChatGPT Plus','Personal ChatGPT plan with Codex.',(SELECT id FROM sources WHERE name='OpenAI ChatGPT pricing'),'SUBSCRIPTION',20,NULL,'USD','No annual price published.','GPT-6 Sol; GPT-6 Luna; other availability may vary','NO','YES','Expanded Codex allowance; model- and task-dependent estimates are published','Rolling five-hour windows; weekly limits may apply','Provider estimates vary by model; no guaranteed token allowance','Usage varies by task, context, reasoning, speed and tools; credits may extend eligible usage.','ChatGPT availability varies by supported country.',1,'ACTIVE','2026-09-29'),
 ((SELECT id FROM providers WHERE name='OpenAI'),'ChatGPT Pro 5x','Current lower Pro tier with Codex.',(SELECT id FROM sources WHERE name='OpenAI ChatGPT pricing'),'SUBSCRIPTION',100,NULL,'USD','No annual price published.','GPT-6 Astra; GPT-6 Sol; GPT-6 Luna','NO','YES','5x Plus usage; exact token equivalent not published','No five-hour limit currently; weekly/fair-use controls apply','5x Plus, not a token quantity','Shared agentic allowance and fair-use controls; credits may extend usage.','ChatGPT availability varies by supported country.',1,'ACTIVE','2026-09-29'),
 ((SELECT id FROM providers WHERE name='OpenAI'),'ChatGPT Pro 20x','Higher Pro tier; new sign-ups temporarily paused on verification date.',(SELECT id FROM sources WHERE name='OpenAI ChatGPT pricing'),'SUBSCRIPTION',200,NULL,'USD','No annual price published; new sign-ups paused as of 2026-09-10.','GPT-6 Astra; GPT-6 Sol; GPT-6 Luna','NO','YES','20x Plus usage; exact token equivalent not published','No five-hour limit currently; weekly/fair-use controls apply','20x Plus, not a token quantity','Shared agentic allowance and fair-use controls.','Existing subscribers continue; new sign-ups temporarily paused.',1,'LIMITED','2026-09-29'),
 ((SELECT id FROM providers WHERE name='OpenAI'),'ChatGPT Business Standard','Business workspace standard seat.',(SELECT id FROM sources WHERE name='OpenAI ChatGPT pricing'),'SUBSCRIPTION',25,240,'USD','$20/user/month with annual commitment; minimum two standard seats.','GPT-6 Astra; GPT-6.1 Sol; GPT-6 Sol; GPT-6 Luna','NO','YES','Published Codex estimates broadly match Plus; shared workspace allowance','Rolling five-hour windows; weekly limits may apply','No guaranteed token allowance','Local and cloud usage share allowance; workspace controls apply.','Business availability and billing can vary by country.',1,'ACTIVE','2026-09-29'),
 ((SELECT id FROM providers WHERE name='Anthropic'),'Claude Free','Free Claude app plan; Claude Code not included.',(SELECT id FROM sources WHERE name='Anthropic Claude pricing'),'FREE',0,NULL,'USD',NULL,'Claude Sonnet; Claude Haiku','NO','NO','Limited; exact capacity not published','Provider-displayed reset','No exact request or token allowance','Subject to capacity and usage policies.','Claude supported-country list applies.',0,'ACTIVE','2026-09-29'),
 ((SELECT id FROM providers WHERE name='Anthropic'),'Claude Pro','Personal Claude plan with Claude Code.',(SELECT id FROM sources WHERE name='Anthropic Claude pricing'),'SUBSCRIPTION',20,200,'USD','$17 effective monthly when billed annually.','Claude Opus; Sonnet; Haiku','NO','YES','At least 5x Free per five-hour session; shared Claude and Claude Code pool','Rolling five-hour session plus weekly limits','5x Free, not a token quantity','Usage varies with model, context, attachments, tools and repository size; additional caps may apply.','Claude supported-country list applies.',1,'ACTIVE','2026-09-29'),
 ((SELECT id FROM providers WHERE name='Anthropic'),'Claude Max 5x','Higher-usage personal Claude and Claude Code plan.',(SELECT id FROM sources WHERE name='Anthropic Claude pricing'),'SUBSCRIPTION',100,NULL,'USD',NULL,'Claude Opus; Sonnet; Haiku; limited Fable via credits','NO','YES','5x Pro usage per session','Rolling five-hour session plus weekly limits','5x Pro, not a token quantity','Shared Claude and Claude Code pool; model and feature caps may apply.','Claude supported-country list applies.',1,'ACTIVE','2026-09-29'),
 ((SELECT id FROM providers WHERE name='Anthropic'),'Claude Max 20x','Highest published personal Claude and Claude Code usage tier.',(SELECT id FROM sources WHERE name='Anthropic Claude pricing'),'SUBSCRIPTION',200,NULL,'USD',NULL,'Claude Opus; Sonnet; Haiku; limited Fable via credits','NO','YES','20x Pro usage per session','Rolling five-hour session plus weekly limits','20x Pro, not a token quantity','Shared Claude and Claude Code pool; model and feature caps may apply.','Claude supported-country list applies.',1,'ACTIVE','2026-09-29'),
 ((SELECT id FROM providers WHERE name='Z.ai'),'GLM Coding Plan Lite','Coding-only subscription endpoint for supported tools.',(SELECT id FROM sources WHERE name='Z.ai Coding Plan overview'),'SUBSCRIPTION',18,151.20,'USD','$12.60/month equivalent on annual billing.','GLM-5.3; GLM-5.3-Flash','LIMITED','YES','2,000 credits per rolling 5 hours and 10,000 per week','Dynamic five-hour refresh; weekly cycle from order time','2,000 credits/5h; 10,000/week','Single-person interactive coding only; no apps, bots, SaaS, proxy, resale or account sharing.','Global Z.ai channel; exact country list not published.',1,'ACTIVE','2026-09-29'),
 ((SELECT id FROM providers WHERE name='Z.ai'),'GLM Coding Plan Pro','Six-times-Lite coding subscription.',(SELECT id FROM sources WHERE name='Z.ai Coding Plan overview'),'SUBSCRIPTION',80,672,'USD','$56/month equivalent on annual billing.','GLM-5.3; GLM-5.3-Flash','LIMITED','YES','12,000 credits per rolling 5 hours and 60,000 per week','Dynamic five-hour refresh; weekly cycle from order time','12,000 credits/5h; 60,000/week','Single-person interactive coding only; no apps, bots, SaaS, proxy, resale or account sharing.','Global Z.ai channel; exact country list not published.',1,'ACTIVE','2026-09-29'),
 ((SELECT id FROM providers WHERE name='Z.ai'),'GLM Coding Plan Max','Fourteen-times-Lite coding subscription.',(SELECT id FROM sources WHERE name='Z.ai Coding Plan overview'),'SUBSCRIPTION',168,1411.20,'USD','$117.60/month equivalent on annual billing.','GLM-5.3; GLM-5.3-Flash','LIMITED','YES','28,000 credits per rolling 5 hours and 140,000 per week','Dynamic five-hour refresh; weekly cycle from order time','28,000 credits/5h; 140,000/week','Single-person interactive coding only; no apps, bots, SaaS, proxy, resale or account sharing.','Global Z.ai channel; exact country list not published.',1,'ACTIVE','2026-09-29'),
 ((SELECT id FROM providers WHERE name='Google'),'Gemini Code Assist Standard','Developer seat for Gemini CLI and IDE agent mode.',(SELECT id FROM sources WHERE name='Google Gemini Code Assist pricing'),'SUBSCRIPTION',22.80,NULL,'USD','$19/license/month with a 12-month commitment, billed monthly.','Current Code Assist/CLI model selection; fixed roster not promised','NO','YES','1,500 model requests per user per day across CLI and agent mode','Daily; exact reset clock not published','1,500 model requests/user/day; one prompt may use multiple requests','Demand throttling and availability controls apply; separate API key can be used after quota.','Global processing; customer-selected serving region unavailable.',1,'ACTIVE','2026-09-29'),
 ((SELECT id FROM providers WHERE name='Google'),'Gemini Code Assist Enterprise','Higher-quota Code Assist developer seat.',(SELECT id FROM sources WHERE name='Google Gemini Code Assist pricing'),'SUBSCRIPTION',54,NULL,'USD','$45/license/month with a 12-month commitment, billed monthly.','Current Code Assist/CLI model selection; fixed roster not promised','NO','YES','2,000 model requests per user per day across CLI and agent mode','Daily; exact reset clock not published','2,000 model requests/user/day; one prompt may use multiple requests','Demand throttling and availability controls apply.','Global processing; customer-selected serving region unavailable.',1,'ACTIVE','2026-09-29'),
 ((SELECT id FROM providers WHERE name='Alibaba Coding Plan'),'Coding Plan Pro (International)','Limited-quantity interactive coding plan.',(SELECT id FROM sources WHERE name='Alibaba Coding Plan'),'SUBSCRIPTION',50,NULL,'USD','Restocked daily and may sell out.','Qwen3.7/3.6/3.5; Qwen Coder; GLM; Kimi; MiniMax models listed by provider','LIMITED','YES','6,000 model calls/5h; 45,000/week; 90,000/month','Rolling five-hour; Monday 00:00 UTC+8 weekly; renewal-date monthly','6,000 calls/5h; 45,000/week; 90,000/month','Interactive coding tools only; no automated scripts, backends or batch API use.','International plan and endpoint; separate Beijing plan exists.',1,'LIMITED','2026-09-29'),
 ((SELECT id FROM providers WHERE name='Alibaba Token Plan'),'Token Plan Personal Standard','Singapore-region credit subscription for developer agents.',(SELECT id FROM sources WHERE name='Alibaba Token Plan'),'SUBSCRIPTION',18,NULL,'USD','Limited-time price; list price $25.','Multi-provider text, multimodal, speech and generation models','LIMITED','YES','10,000 credits per seven days; 3–4 concurrent agents','Every seven days','10,000 credits/7 days','Unused quota does not roll over.','International plan is Singapore-region only.',1,'ACTIVE','2026-09-29'),
 ((SELECT id FROM providers WHERE name='MiniMax Token Plan (minimax.io)'),'Token Plan Plus','Individual developer token subscription.',(SELECT id FROM sources WHERE name='MiniMax Token Plan'),'SUBSCRIPTION',20,200,'USD','Current annual price.','MiniMax M3; M2.7; image; speech','LIMITED','YES','Approximately 1.7B M3 tokens/month; shared multimodal quota','Rolling five-hour and weekly windows; monthly entitlement','~1.7B M3 tokens/month; model-specific call estimates are approximate','Interactive individual use; dynamic peak throttling; PAYG recommended for production.','International MiniMax platform terms apply.',1,'ACTIVE','2026-09-29'),
 ((SELECT id FROM providers WHERE name='MiniMax Token Plan (minimax.io)'),'Token Plan Max','Higher-quota individual developer token subscription.',(SELECT id FROM sources WHERE name='MiniMax Token Plan'),'SUBSCRIPTION',50,500,'USD','Current annual price.','MiniMax M3; M2.7; image; speech; limited video','LIMITED','YES','Approximately 5.1B M3 tokens/month; shared multimodal quota','Rolling five-hour and weekly windows; monthly entitlement','~5.1B M3 tokens/month; model-specific call estimates are approximate','Interactive individual use; dynamic peak throttling; PAYG recommended for production.','International MiniMax platform terms apply.',1,'ACTIVE','2026-09-29'),
 ((SELECT id FROM providers WHERE name='MiniMax Token Plan (minimax.io)'),'Token Plan Ultra','Highest individual developer token subscription.',(SELECT id FROM sources WHERE name='MiniMax Token Plan'),'SUBSCRIPTION',120,1200,'USD','Current annual price.','MiniMax M3; M2.7; image; speech; limited video','LIMITED','YES','Approximately 12.5B M3 tokens/month; shared multimodal quota','Rolling five-hour and weekly windows; monthly entitlement','~12.5B M3 tokens/month; model-specific call estimates are approximate','Interactive individual use; dynamic peak throttling; PAYG recommended for production.','International MiniMax platform terms apply.',1,'ACTIVE','2026-09-29'),
 ((SELECT id FROM providers WHERE name='Kimi For Coding (kimi.com)'),'Kimi Andante','Kimi membership including Kimi Code.',(SELECT id FROM sources WHERE name='Kimi membership pricing'),'SUBSCRIPTION',49,NULL,'CNY','China-priced membership.','Kimi-for-coding current backend model','LIMITED','YES','Approximately 1x base shared monthly credit pool; absolute credits not public','Rolling five-hour, seven-day and monthly pools','Provider guidance: roughly 300–1,200 requests/5h across plans; tier-specific count unknown','Personal development only; unused weekly/monthly quota does not roll over.','China-priced membership and Kimi terms apply.',1,'ACTIVE','2026-09-29'),
 ((SELECT id FROM providers WHERE name='Kimi For Coding (kimi.com)'),'Kimi Allegretto','Higher Kimi membership with HighSpeed eligibility.',(SELECT id FROM sources WHERE name='Kimi membership pricing'),'SUBSCRIPTION',199,NULL,'CNY','China-priced membership.','Kimi-for-coding; Kimi-for-coding-highspeed','LIMITED','YES','Approximately 4x base shared monthly credit pool; absolute credits not public','Rolling five-hour, seven-day and monthly pools','Provider guidance: roughly 300–1,200 requests/5h across plans; tier-specific count unknown','Personal development only; unused weekly/monthly quota does not roll over.','China-priced membership and Kimi terms apply.',1,'ACTIVE','2026-09-29'),
 ((SELECT id FROM providers WHERE name='OpenCode Go'),'OpenCode Go','Low-cost subscription for curated coding models.',(SELECT id FROM sources WHERE name='OpenCode Go'),'SUBSCRIPTION',10,NULL,'USD',NULL,'Changing curated lineup including GLM, Kimi, MiniMax, Qwen, DeepSeek and others','LIMITED','YES','Model-specific dollar-value allowance; common models $60/month, others $15 or $30','Five-hour cap 20%; weekly 50%; monthly 100% of each model allowance','Dollar-value limits vary by model; no universal token count','One subscriber per workspace; optional Zen PAYG fallback after limits.','Offered through OpenCode account; availability may vary.',1,'ACTIVE','2026-09-29');

WITH links(plan_provider,plan_name,harness,support,note,source) AS (VALUES
 ('OpenAI','ChatGPT Plus','Codex CLI','OFFICIAL','Native ChatGPT sign-in.','OpenAI ChatGPT pricing'),
 ('OpenAI','ChatGPT Pro 5x','Codex CLI','OFFICIAL','Native ChatGPT sign-in.','OpenAI ChatGPT pricing'),
 ('OpenAI','ChatGPT Pro 20x','Codex CLI','OFFICIAL','Native ChatGPT sign-in.','OpenAI ChatGPT pricing'),
 ('OpenAI','ChatGPT Business Standard','Codex CLI','OFFICIAL','Workspace Codex access.','OpenAI ChatGPT pricing'),
 ('Anthropic','Claude Pro','Claude Code','OFFICIAL','Native Claude subscription login.','Anthropic Claude Code plan guide'),
 ('Anthropic','Claude Max 5x','Claude Code','OFFICIAL','Native Claude subscription login.','Anthropic Claude Code plan guide'),
 ('Anthropic','Claude Max 20x','Claude Code','OFFICIAL','Native Claude subscription login.','Anthropic Claude Code plan guide'),
 ('Anthropic','Claude Pro','OpenCode','UNSUPPORTED','Anthropic prohibits third-party subscription-token use.','OpenCode provider documentation'),
 ('Z.ai','GLM Coding Plan Lite','ZCode','OFFICIAL','First-party plan and agent.','Z.ai Coding Plan overview'),
 ('Z.ai','GLM Coding Plan Lite','Claude Code','DOCUMENTED_THIRD_PARTY','Listed supported coding tool.','Z.ai Coding Plan overview'),
 ('Z.ai','GLM Coding Plan Lite','Codex CLI','DOCUMENTED_THIRD_PARTY','Listed supported coding tool.','Z.ai Coding Plan overview'),
 ('Z.ai','GLM Coding Plan Lite','OpenCode','DOCUMENTED_THIRD_PARTY','Listed supported coding tool.','Z.ai Coding Plan overview'),
 ('Z.ai','GLM Coding Plan Lite','Pi','DOCUMENTED_THIRD_PARTY','Listed supported coding tool.','Z.ai Coding Plan overview'),
 ('Z.ai','GLM Coding Plan Lite','Hermes Agent','DOCUMENTED_THIRD_PARTY','Best-effort supported list; temporary rate limits possible.','Z.ai Coding Plan overview'),
 ('Z.ai','GLM Coding Plan Pro','ZCode','OFFICIAL','First-party plan and agent.','Z.ai Coding Plan overview'),
 ('Z.ai','GLM Coding Plan Pro','Claude Code','DOCUMENTED_THIRD_PARTY','Listed supported coding tool.','Z.ai Coding Plan overview'),
 ('Z.ai','GLM Coding Plan Pro','Codex CLI','DOCUMENTED_THIRD_PARTY','Listed supported coding tool.','Z.ai Coding Plan overview'),
 ('Z.ai','GLM Coding Plan Pro','OpenCode','DOCUMENTED_THIRD_PARTY','Listed supported coding tool.','Z.ai Coding Plan overview'),
 ('Z.ai','GLM Coding Plan Pro','Pi','DOCUMENTED_THIRD_PARTY','Listed supported coding tool.','Z.ai Coding Plan overview'),
 ('Z.ai','GLM Coding Plan Pro','Hermes Agent','DOCUMENTED_THIRD_PARTY','Best-effort supported list; temporary rate limits possible.','Z.ai Coding Plan overview'),
 ('Z.ai','GLM Coding Plan Max','ZCode','OFFICIAL','First-party plan and agent.','Z.ai Coding Plan overview'),
 ('Z.ai','GLM Coding Plan Max','Claude Code','DOCUMENTED_THIRD_PARTY','Listed supported coding tool.','Z.ai Coding Plan overview'),
 ('Z.ai','GLM Coding Plan Max','Codex CLI','DOCUMENTED_THIRD_PARTY','Listed supported coding tool.','Z.ai Coding Plan overview'),
 ('Z.ai','GLM Coding Plan Max','OpenCode','DOCUMENTED_THIRD_PARTY','Listed supported coding tool.','Z.ai Coding Plan overview'),
 ('Z.ai','GLM Coding Plan Max','Pi','DOCUMENTED_THIRD_PARTY','Listed supported coding tool.','Z.ai Coding Plan overview'),
 ('Google','Gemini Code Assist Standard','Gemini CLI','OFFICIAL','First-party Code Assist entitlement.','Google Gemini Code Assist pricing'),
 ('Google','Gemini Code Assist Enterprise','Gemini CLI','OFFICIAL','First-party Code Assist entitlement.','Google Gemini Code Assist pricing'),
 ('Alibaba Coding Plan','Coding Plan Pro (International)','Qwen Code','OFFICIAL','Native plan authentication.','Alibaba Coding Plan'),
 ('Alibaba Coding Plan','Coding Plan Pro (International)','Claude Code','DOCUMENTED_THIRD_PARTY','Officially listed interactive tool.','Alibaba Coding Plan'),
 ('Alibaba Coding Plan','Coding Plan Pro (International)','Codex CLI','DOCUMENTED_THIRD_PARTY','Officially listed interactive tool.','Alibaba Coding Plan'),
 ('Alibaba Coding Plan','Coding Plan Pro (International)','OpenCode','DOCUMENTED_THIRD_PARTY','Officially listed interactive tool.','Alibaba Coding Plan'),
 ('Alibaba Coding Plan','Coding Plan Pro (International)','Cline','DOCUMENTED_THIRD_PARTY','Officially listed interactive tool.','Alibaba Coding Plan'),
 ('Alibaba Token Plan','Token Plan Personal Standard','Qwen Code','OFFICIAL','Native plan authentication.','Alibaba Token Plan'),
 ('Alibaba Token Plan','Token Plan Personal Standard','Claude Code','API_ROUTE','Anthropic-compatible subscription endpoint.','Alibaba Token Plan'),
 ('Alibaba Token Plan','Token Plan Personal Standard','Codex CLI','API_ROUTE','OpenAI-compatible subscription endpoint.','Alibaba Token Plan'),
 ('MiniMax Token Plan (minimax.io)','Token Plan Plus','Claude Code','DOCUMENTED_THIRD_PARTY','Provider documents subscription key setup.','MiniMax Token Plan'),
 ('MiniMax Token Plan (minimax.io)','Token Plan Plus','Cline','DOCUMENTED_THIRD_PARTY','Provider documents subscription key setup.','MiniMax Token Plan'),
 ('MiniMax Token Plan (minimax.io)','Token Plan Max','Claude Code','DOCUMENTED_THIRD_PARTY','Provider documents subscription key setup.','MiniMax Token Plan'),
 ('MiniMax Token Plan (minimax.io)','Token Plan Ultra','Claude Code','DOCUMENTED_THIRD_PARTY','Provider documents subscription key setup.','MiniMax Token Plan'),
 ('Kimi For Coding (kimi.com)','Kimi Andante','OpenCode','DOCUMENTED_THIRD_PARTY','Provider documents compatible-agent key use.','Kimi Code membership guide'),
 ('Kimi For Coding (kimi.com)','Kimi Andante','Claude Code','DOCUMENTED_THIRD_PARTY','Provider documents Anthropic-compatible endpoint.','Kimi Code membership guide'),
 ('Kimi For Coding (kimi.com)','Kimi Andante','Hermes Agent','DOCUMENTED_THIRD_PARTY','Provider lists compatible-agent use.','Kimi Code membership guide'),
 ('OpenCode Go','OpenCode Go','OpenCode','OFFICIAL','First-party plan and harness.','OpenCode Go'),
 ('OpenCode Go','OpenCode Go','Claude Code','API_ROUTE','Provider says any compatible agent can use the endpoint.','OpenCode Go'),
 ('OpenCode Go','OpenCode Go','Pi','API_ROUTE','Provider says any compatible agent can use the endpoint.','OpenCode Go')
)
INSERT INTO plan_harness_compatibility(plan_id,harness_id,support_level,note,source_id,verified_at)
SELECT pl.id,h.id,l.support,l.note,s.id,'2026-09-29' FROM links l
JOIN providers p ON p.name=l.plan_provider JOIN plans pl ON pl.provider_id=p.id AND pl.name=l.plan_name
JOIN harnesses h ON h.name=l.harness JOIN sources s ON s.name=l.source;

WITH routes(family,provider,plan_provider,plan_name,route_name,route_type,billing,detail,source) AS (VALUES
 ('GLM','Z.ai','Z.ai','GLM Coding Plan Lite','Z.ai Coding Plan','SUBSCRIPTION','Fixed subscription; credits and rolling limits','Dedicated coding endpoints for supported interactive tools; not a general production API.','Z.ai Coding Plan overview'),
 ('GLM','Z.ai',NULL,NULL,'Z.ai PAYG API','DIRECT_API','Exact per-token pricing by model','General OpenAI-compatible API endpoint; account-specific rate limits.','Z.ai API pricing'),
 ('GLM','OpenRouter',NULL,NULL,'OpenRouter','AGGREGATOR','Per-token route pricing','OpenRouter API route; provider and model availability vary.','OpenRouter model API'),
 ('GPT','OpenAI','OpenAI','ChatGPT Plus','ChatGPT / Codex subscription','SUBSCRIPTION','Fixed subscription with variable allowance','Native Codex sign-in; API usage is separate.','OpenAI ChatGPT pricing'),
 ('GPT','OpenAI',NULL,NULL,'OpenAI API','DIRECT_API','Per-token pricing','Direct API key; Codex local surfaces supported, subscription cloud features excluded.','OpenAI API pricing'),
 ('GPT','OpenRouter',NULL,NULL,'OpenRouter','AGGREGATOR','Per-token route pricing','Only models currently offered by OpenRouter.','OpenRouter model API'),
 ('Claude','Anthropic','Anthropic','Claude Pro','Claude subscription','SUBSCRIPTION','Fixed subscription with five-hour and weekly limits','Native Claude Code login; API usage is separate.','Anthropic Claude Code plan guide'),
 ('Claude','Anthropic',NULL,NULL,'Anthropic API','DIRECT_API','Per-token pricing','Direct Console/API key with account rate limits.','Anthropic Claude pricing'),
 ('Claude','OpenRouter',NULL,NULL,'OpenRouter','AGGREGATOR','Per-token route pricing','Anthropic-compatible aggregator route.','OpenRouter model API'),
 ('Gemini','Google','Google','Gemini Code Assist Standard','Gemini Code Assist','SUBSCRIPTION','Fixed per-seat subscription with daily requests','Official Gemini CLI entitlement; consumer Google plans no longer provide CLI access.','Google Gemini Code Assist pricing'),
 ('Gemini','Google',NULL,NULL,'Gemini Developer API','DIRECT_API','Free tier or per-token paid tier by model','Gemini API key in Gemini CLI; separate from Code Assist subscription.','Google Gemini API pricing'),
 ('Qwen','Alibaba Coding Plan','Alibaba Coding Plan','Coding Plan Pro (International)','Alibaba Coding Plan','SUBSCRIPTION','Fixed subscription with call limits','Dedicated coding endpoint; interactive tools only.','Alibaba Coding Plan'),
 ('Qwen','Alibaba Cloud',NULL,NULL,'Alibaba ModelStudio API','DIRECT_API','Per-token or Token Plan billing','Standard ModelStudio API route, separate from Coding Plan.','Alibaba Token Plan'),
 ('Qwen','OpenRouter',NULL,NULL,'OpenRouter','AGGREGATOR','Per-token route pricing','Aggregator route for currently listed Qwen models.','OpenRouter model API'),
 ('MiniMax','MiniMax (minimax.io)','MiniMax Token Plan (minimax.io)','Token Plan Plus','MiniMax Token Plan','SUBSCRIPTION','Fixed subscription with approximate model-equivalent quota','Subscription key for documented interactive tools.','MiniMax Token Plan'),
 ('MiniMax','MiniMax (minimax.io)',NULL,NULL,'MiniMax PAYG API','DIRECT_API','Per-token pricing by model/context','Production-recommended direct API route.','MiniMax Token Plan'),
 ('Kimi','Kimi For Coding (kimi.com)','Kimi For Coding (kimi.com)','Kimi Andante','Kimi membership / Kimi Code','SUBSCRIPTION','Fixed membership with shared credits','Coding-only OpenAI- and Anthropic-compatible endpoints for personal development.','Kimi Code membership guide'),
 ('Kimi','Moonshot AI',NULL,NULL,'Moonshot Open Platform API','DIRECT_API','Per-token pricing','Production/API integration route, separate from Kimi membership.','Kimi Code membership guide'),
 ('DeepSeek','DeepSeek',NULL,NULL,'DeepSeek API','DIRECT_API','Per-token pricing with peak/off-peak rates','No current paid coding subscription; compatible API route only.','DeepSeek API pricing'),
 ('DeepSeek','OpenRouter',NULL,NULL,'OpenRouter','AGGREGATOR','Per-token route pricing','Aggregator route for currently listed DeepSeek models.','OpenRouter model API'),
 ('Open models','OpenCode Go','OpenCode Go','OpenCode Go','OpenCode Go','SUBSCRIPTION','Fixed subscription with model-specific dollar-value caps','Curated plan endpoint for OpenCode or compatible agents.','OpenCode Go'),
 ('Open models','OpenCode Zen',NULL,NULL,'OpenCode Zen','AGGREGATOR','PAYG per-token pricing','Optional curated gateway; several promotional free routes may exist.','OpenCode Zen')
)
INSERT INTO model_access_routes(model_family,provider_id,plan_id,route_name,route_type,billing_basis,access_detail,source_id,verified_at)
SELECT r.family,p.id,pl.id,r.route_name,r.route_type,r.billing,r.detail,s.id,'2026-09-29'
FROM routes r LEFT JOIN providers p ON p.name=r.provider
LEFT JOIN providers pp ON pp.name=r.plan_provider LEFT JOIN plans pl ON pl.provider_id=pp.id AND pl.name=r.plan_name
JOIN sources s ON s.name=r.source;
