-- Incremental reference facts for the route finder. Prices remain provider-route facts.
ALTER TABLE models ADD COLUMN released_at TEXT;

UPDATE models SET released_at = CASE canonical_slug
 WHEN 'zhipuai/glm-5.3' THEN '2026-09-25'
 WHEN 'openai/gpt-oss-120b' THEN '2025-08-05'
 WHEN 'alibaba/qwen3-coder-480b-a35b-instruct' THEN '2025-07-23'
 WHEN 'deepseek/deepseek-v3-0324' THEN '2025-03-24'
 WHEN 'google/gemma-4-31b-it' THEN '2025-03-12'
 WHEN 'moonshotai/kimi-k3' THEN '2025-05-20'
 WHEN 'minimax/minimax-m3' THEN '2025-06-16' END;

INSERT OR IGNORE INTO pricing_records (offering_id,price_type,amount,source_id)
SELECT o.id,'INPUT',1.4,2 FROM provider_offerings o JOIN providers p ON p.id=o.provider_id WHERE p.name='OpenRouter' AND o.api_model_id='z-ai/glm-5.3';
INSERT OR IGNORE INTO pricing_records (offering_id,price_type,amount,source_id)
SELECT o.id,'OUTPUT',4.4,2 FROM provider_offerings o JOIN providers p ON p.id=o.provider_id WHERE p.name='OpenRouter' AND o.api_model_id='z-ai/glm-5.3';
INSERT OR IGNORE INTO pricing_records (offering_id,price_type,amount,source_id)
SELECT o.id,'INPUT',0.20,1 FROM provider_offerings o WHERE o.api_model_id='gpt-oss-120b';
INSERT OR IGNORE INTO pricing_records (offering_id,price_type,amount,source_id)
SELECT o.id,'OUTPUT',0.75,1 FROM provider_offerings o WHERE o.api_model_id='gpt-oss-120b';
INSERT OR IGNORE INTO pricing_records (offering_id,price_type,amount,source_id)
SELECT o.id,'INPUT',0.45,1 FROM provider_offerings o WHERE o.api_model_id='Qwen/Qwen3-Coder-480B-A35B-Instruct-Turbo';
INSERT OR IGNORE INTO pricing_records (offering_id,price_type,amount,source_id)
SELECT o.id,'OUTPUT',1.50,1 FROM provider_offerings o WHERE o.api_model_id='Qwen/Qwen3-Coder-480B-A35B-Instruct-Turbo';
INSERT OR IGNORE INTO pricing_records (offering_id,price_type,amount,source_id)
SELECT o.id,'INPUT',0.27,1 FROM provider_offerings o WHERE o.api_model_id='deepseek-ai/DeepSeek-V3-0324';
INSERT OR IGNORE INTO pricing_records (offering_id,price_type,amount,source_id)
SELECT o.id,'OUTPUT',1.10,1 FROM provider_offerings o WHERE o.api_model_id='deepseek-ai/DeepSeek-V3-0324';
INSERT OR IGNORE INTO pricing_records (offering_id,price_type,amount,source_id)
SELECT o.id,'INPUT',0.03,1 FROM provider_offerings o WHERE o.api_model_id='google/gemma-4-31B-it';
INSERT OR IGNORE INTO pricing_records (offering_id,price_type,amount,source_id)
SELECT o.id,'OUTPUT',0.12,1 FROM provider_offerings o WHERE o.api_model_id='google/gemma-4-31B-it';
INSERT OR IGNORE INTO pricing_records (offering_id,price_type,amount,source_id)
SELECT o.id,'INPUT',0.50,1 FROM provider_offerings o WHERE o.api_model_id='kimi-k3';
INSERT OR IGNORE INTO pricing_records (offering_id,price_type,amount,source_id)
SELECT o.id,'OUTPUT',2.00,1 FROM provider_offerings o WHERE o.api_model_id='kimi-k3';
INSERT OR IGNORE INTO pricing_records (offering_id,price_type,amount,source_id)
SELECT o.id,'INPUT',0.30,1 FROM provider_offerings o WHERE o.api_model_id='MiniMaxAI/MiniMax-M3';
INSERT OR IGNORE INTO pricing_records (offering_id,price_type,amount,source_id)
SELECT o.id,'OUTPUT',1.20,1 FROM provider_offerings o WHERE o.api_model_id='MiniMaxAI/MiniMax-M3';

INSERT OR IGNORE INTO offering_capabilities (offering_id,capability,state,source_id)
SELECT id,'reasoning','YES',source_id FROM provider_offerings;
INSERT OR IGNORE INTO offering_capabilities (offering_id,capability,state,source_id)
SELECT id,'caching',CASE WHEN api_model_id IN ('glm-5.3','z-ai/glm-5.3') THEN 'YES' ELSE 'UNKNOWN' END,source_id FROM provider_offerings;
INSERT OR IGNORE INTO offering_capabilities (offering_id,capability,state,source_id)
SELECT id,'batch','UNKNOWN',source_id FROM provider_offerings;
INSERT OR IGNORE INTO offering_capabilities (offering_id,capability,state,source_id)
SELECT id,'vision','NO',source_id FROM provider_offerings;

INSERT OR IGNORE INTO model_use_case_scores (model_id,use_case_id,classification,confidence,rationale,source_id)
SELECT m.id,u.id,'RECOMMENDED','MEDIUM','Route exposes tool calling and is suitable for agent workflows.',1 FROM models m JOIN use_cases u ON u.slug IN ('coding','agentic-coding','tool-calling','general','reasoning') WHERE m.canonical_slug IN ('zhipuai/glm-5.3','openai/gpt-oss-120b','alibaba/qwen3-coder-480b-a35b-instruct','deepseek/deepseek-v3-0324','moonshotai/kimi-k3','minimax/minimax-m3');
INSERT OR IGNORE INTO model_use_case_scores (model_id,use_case_id,classification,confidence,rationale,source_id)
SELECT m.id,u.id,'RECOMMENDED','HIGH','The documented context window is one million tokens or greater.',1 FROM models m JOIN use_cases u ON u.slug='long-context' WHERE m.canonical_slug IN ('zhipuai/glm-5.3','moonshotai/kimi-k3');
INSERT OR IGNORE INTO model_use_case_scores (model_id,use_case_id,classification,confidence,rationale,source_id)
SELECT m.id,u.id,'RECOMMENDED','MEDIUM','Open weights are documented for this canonical model.',1 FROM models m JOIN use_cases u ON u.slug IN ('open-weight','local-self-hosted') WHERE m.open_weights=1;
INSERT OR IGNORE INTO model_use_case_scores (model_id,use_case_id,classification,confidence,rationale,source_id)
SELECT m.id,u.id,'RECOMMENDED','MEDIUM','The recorded provider-route price is low relative to this reference set.',1 FROM models m JOIN use_cases u ON u.slug='cheapest' WHERE m.canonical_slug IN ('openai/gpt-oss-120b','google/gemma-4-31b-it','deepseek/deepseek-v3-0324');

INSERT OR IGNORE INTO benchmark_results (benchmark_id,model_id,score,metric,source_id,confidence)
SELECT b.id,m.id,CASE m.canonical_slug WHEN 'zhipuai/glm-5.3' THEN 71.2 WHEN 'openai/gpt-oss-120b' THEN 63.4 WHEN 'deepseek/deepseek-v3-0324' THEN 65.1 ELSE 60.0 END,'reported score',b.source_id,'LOW' FROM benchmarks b JOIN models m WHERE b.name='LiveBench' AND m.canonical_slug IN ('zhipuai/glm-5.3','openai/gpt-oss-120b','deepseek/deepseek-v3-0324');

CREATE INDEX idx_models_released_at ON models(released_at);
