-- First-party price observations for exact routes with live, explicit official
-- price tables. Prices remain per route/class/context tier; aggregator history
-- is retained and disagreements receive a review item.
INSERT OR IGNORE INTO sources(name,url,source_type,reliability) VALUES
 ('OpenAI API pricing','https://platform.openai.com/pricing','official_provider','HIGH'),
 ('Google Gemini API pricing','https://ai.google.dev/gemini-api/docs/pricing','official_provider','HIGH'),
 ('xAI API pricing','https://docs.x.ai/developers/pricing','official_provider','HIGH'),
 ('MiniMax API pricing','https://platform.minimax.io/subscribe/token-plan?tab=api-enterprise','official_provider','HIGH'),
 ('Z.ai API pricing','https://docs.z.ai/guides/overview/pricing','official_provider','HIGH'),
 ('Mistral API pricing','https://docs.mistral.ai/inference/pricing','official_provider','HIGH'),
 ('Alibaba Cloud Model Studio pricing','https://www.alibabacloud.com/help/en/model-studio/model-pricing','official_provider','HIGH');
UPDATE sources SET source_type='official_provider',reliability='HIGH'
WHERE url IN ('https://platform.openai.com/pricing','https://ai.google.dev/gemini-api/docs/pricing',
 'https://docs.x.ai/developers/pricing','https://platform.minimax.io/subscribe/token-plan',
 'https://platform.minimax.io/subscribe/token-plan?tab=api-enterprise','https://docs.z.ai/guides/overview/pricing',
 'https://docs.mistral.ai/inference/pricing','https://www.alibabacloud.com/help/en/model-studio/model-pricing');
ALTER TABLE offers ADD COLUMN promotion_current_amount NUMERIC;
ALTER TABLE offers ADD COLUMN promotion_reference_amount NUMERIC;
ALTER TABLE offers ADD COLUMN promotion_currency TEXT;
ALTER TABLE offers ADD COLUMN promotion_unit TEXT;
ALTER TABLE offers ADD COLUMN promotion_discount_percent NUMERIC;
ALTER TABLE offers ADD COLUMN region_restrictions TEXT;
ALTER TABLE offers ADD COLUMN conditions TEXT;

-- Preserve previous current observations as history before installing first-party
-- prices. Tier thresholds denote the lower bound of the higher context tier.
UPDATE pricing_records SET valid_until='2026-09-30',fetched_at='2026-09-30'
WHERE valid_until IS NULL AND EXISTS (
 SELECT 1 FROM provider_offerings o JOIN providers p ON p.id=o.provider_id
 WHERE o.id=pricing_records.offering_id AND (
   (p.name='OpenAI' AND o.api_model_id IN ('gpt-6-sol','gpt-6-luna')) OR
   (p.name='Google' AND o.api_model_id='gemini-3.1-pro-preview') OR
   (p.name='xAI' AND o.api_model_id='grok-4.6') OR
   (p.name='MiniMax (minimax.io)' AND o.api_model_id='MiniMax-M3') OR
   (p.name='Z.ai' AND o.api_model_id='glm-5.3') OR
   (p.name='Mistral' AND o.api_model_id IN ('mistral-large-3','mistral-medium-3-5')) OR
   (p.name IN ('Alibaba','Alibaba (China)') AND o.api_model_id='qwen3.8-max')
 ));

-- OpenAI GPT-6 prices per 1M tokens, with short/long context kept separate.
INSERT INTO pricing_records(offering_id,price_type,amount,unit,context_threshold,valid_from,source_id,price_note)
SELECT o.id,v.price_type,v.amount,'per_1m_tokens',v.threshold,'2026-09-30',s.id,v.note
FROM (SELECT 'gpt-6-sol' model,'INPUT' price_type,2.00 amount,NULL threshold,'Standard short-context rate (prompts below 200K tokens).' note
 UNION ALL SELECT 'gpt-6-sol','CACHE_READ',0.20,NULL,'Cached input, short context.'
 UNION ALL SELECT 'gpt-6-sol','CACHE_WRITE',2.50,NULL,'Cache write, short context.'
 UNION ALL SELECT 'gpt-6-sol','OUTPUT',10.00,NULL,'Standard short-context rate.'
 UNION ALL SELECT 'gpt-6-sol','INPUT',4.00,200000,'Standard long-context rate (prompts at or above 200K tokens).'
 UNION ALL SELECT 'gpt-6-sol','CACHE_READ',0.40,200000,'Cached input, long context.'
 UNION ALL SELECT 'gpt-6-sol','CACHE_WRITE',5.00,200000,'Cache write, long context.'
 UNION ALL SELECT 'gpt-6-sol','OUTPUT',15.00,200000,'Standard long-context rate.'
 UNION ALL SELECT 'gpt-6-luna','INPUT',0.10,NULL,'Standard short-context rate (prompts below 200K tokens).'
 UNION ALL SELECT 'gpt-6-luna','CACHE_READ',0.01,NULL,'Cached input, short context.'
 UNION ALL SELECT 'gpt-6-luna','CACHE_WRITE',0.125,NULL,'Cache write, short context.'
 UNION ALL SELECT 'gpt-6-luna','OUTPUT',0.50,NULL,'Standard short-context rate.'
 UNION ALL SELECT 'gpt-6-luna','INPUT',0.20,200000,'Standard long-context rate (prompts at or above 200K tokens).'
 UNION ALL SELECT 'gpt-6-luna','CACHE_READ',0.02,200000,'Cached input, long context.'
 UNION ALL SELECT 'gpt-6-luna','CACHE_WRITE',0.25,200000,'Cache write, long context.'
 UNION ALL SELECT 'gpt-6-luna','OUTPUT',0.75,200000,'Standard long-context rate.') v
JOIN provider_offerings o ON o.api_model_id=v.model JOIN providers p ON p.id=o.provider_id AND p.name='OpenAI'
JOIN sources s ON s.name='OpenAI API pricing';

-- Gemini 3.1 Pro Preview Standard rates and its independently priced Batch tier.
INSERT INTO pricing_records(offering_id,price_type,amount,unit,context_threshold,valid_from,source_id,price_note)
SELECT o.id,v.price_type,v.amount,'per_1m_tokens',v.threshold,'2026-09-30',s.id,v.note
FROM (SELECT 'INPUT' price_type,2.00 amount,NULL threshold,'Standard, prompts up to 200K tokens.' note
 UNION ALL SELECT 'OUTPUT',12.00,NULL,'Standard, prompts up to 200K tokens.'
 UNION ALL SELECT 'CACHE_READ',0.20,NULL,'Input cache rate, prompts up to 200K tokens.'
 UNION ALL SELECT 'INPUT',4.00,200000,'Standard, prompts over 200K tokens.'
 UNION ALL SELECT 'OUTPUT',18.00,200000,'Standard, prompts over 200K tokens.'
 UNION ALL SELECT 'CACHE_READ',0.40,200000,'Input cache rate, prompts over 200K tokens.'
 UNION ALL SELECT 'BATCH_INPUT',1.00,NULL,'Batch, prompts up to 200K tokens; kept separate from standard input.'
 UNION ALL SELECT 'BATCH_OUTPUT',6.00,NULL,'Batch, prompts up to 200K tokens; kept separate from standard output.'
 UNION ALL SELECT 'BATCH_INPUT',2.00,200000,'Batch, prompts over 200K tokens.'
 UNION ALL SELECT 'BATCH_OUTPUT',9.00,200000,'Batch, prompts over 200K tokens.') v
JOIN provider_offerings o ON o.api_model_id='gemini-3.1-pro-preview' JOIN providers p ON p.id=o.provider_id AND p.name='Google'
JOIN sources s ON s.name='Google Gemini API pricing';

-- xAI Grok 4.6 exact global rates. Its official page states batch is unsupported.
INSERT INTO pricing_records(offering_id,price_type,amount,unit,context_threshold,valid_from,source_id,price_note)
SELECT o.id,v.price_type,v.amount,'per_1m_tokens',v.threshold,'2026-09-30',s.id,v.note
FROM (SELECT 'INPUT' price_type,2.00 amount,NULL threshold,'Global endpoint, prompt below 200K tokens.' note
 UNION ALL SELECT 'CACHE_READ',0.50,NULL,'Global endpoint, cached input below 200K tokens.'
 UNION ALL SELECT 'OUTPUT',6.00,NULL,'Global endpoint, prompt below 200K tokens.'
 UNION ALL SELECT 'INPUT',4.00,200000,'Global endpoint, long-context prompt at or above 200K tokens.'
 UNION ALL SELECT 'CACHE_READ',1.00,200000,'Global endpoint, cached input at or above 200K tokens.'
 UNION ALL SELECT 'OUTPUT',12.00,200000,'Global endpoint, long-context prompt at or above 200K tokens.') v
JOIN provider_offerings o ON o.api_model_id='grok-4.6' JOIN providers p ON p.id=o.provider_id AND p.name='xAI'
JOIN sources s ON s.name='xAI API pricing';

-- MiniMax M3 Standard token prices; context tiers and cache reads stay distinct.
INSERT INTO pricing_records(offering_id,price_type,amount,unit,context_threshold,valid_from,source_id,price_note)
SELECT o.id,v.price_type,v.amount,'per_1m_tokens',v.threshold,'2026-09-30',s.id,v.note
FROM (SELECT 'INPUT' price_type,0.60 amount,NULL threshold,'Standard rate, context up to 512K.' note
 UNION ALL SELECT 'OUTPUT',2.40,NULL,'Standard rate, context up to 512K.'
 UNION ALL SELECT 'CACHE_READ',0.12,NULL,'Cache read, context up to 512K.'
 UNION ALL SELECT 'INPUT',1.20,512000,'Standard rate, context above 512K through 1M.'
 UNION ALL SELECT 'OUTPUT',4.80,512000,'Standard rate, context above 512K through 1M.'
 UNION ALL SELECT 'CACHE_READ',0.24,512000,'Cache read, context above 512K through 1M.') v
JOIN provider_offerings o ON o.api_model_id='MiniMax-M3' JOIN providers p ON p.id=o.provider_id AND p.name='MiniMax (minimax.io)'
JOIN sources s ON s.name='MiniMax API pricing';

-- Z.ai GLM-5.3. Cached input and explicitly limited-time-free cache storage are
-- separate facts; storage has no invented billing interval or expiry.
INSERT INTO pricing_records(offering_id,price_type,amount,unit,valid_from,source_id,price_note)
SELECT o.id,v.price_type,v.amount,v.unit,'2026-09-30',s.id,v.note
FROM (SELECT 'INPUT' price_type,1.4 amount,'per_1m_tokens' unit,'Official listed input price.' note
 UNION ALL SELECT 'OUTPUT',4.4,'per_1m_tokens','Official listed output price.'
 UNION ALL SELECT 'CACHE_READ',0.26,'per_1m_tokens','Official listed cached input price.'
 UNION ALL SELECT 'CACHE_WRITE',0,'official_unit_unspecified','Official table labels cached input storage Limited-time Free; billing interval and expiry are not published.') v
JOIN provider_offerings o ON o.api_model_id='glm-5.3' JOIN providers p ON p.id=o.provider_id AND p.name='Z.ai'
JOIN sources s ON s.name='Z.ai API pricing';

-- Mistral's official pricing API table gives exact input, cache, and output
-- rates for these public API model IDs.
INSERT INTO pricing_records(offering_id,price_type,amount,unit,valid_from,source_id,price_note)
SELECT o.id,v.price_type,v.amount,'per_1m_tokens','2026-09-30',s.id,'Official Mistral standard API price per 1M tokens.'
FROM (SELECT 'mistral-large-3' model,'INPUT' price_type,0.5 amount
 UNION ALL SELECT 'mistral-large-3','CACHE_READ',0.05
 UNION ALL SELECT 'mistral-large-3','OUTPUT',1.5
 UNION ALL SELECT 'mistral-medium-3-5','INPUT',1.5
 UNION ALL SELECT 'mistral-medium-3-5','CACHE_READ',0.15
 UNION ALL SELECT 'mistral-medium-3-5','OUTPUT',7.5) v
JOIN provider_offerings o ON o.api_model_id=v.model JOIN providers p ON p.id=o.provider_id AND p.name='Mistral'
JOIN sources s ON s.name='Mistral API pricing';

-- Qwen3.8-Max. Alibaba international and China routes are distinct endpoints
-- with region-specific official prices. Batch is recorded only for the
-- international price row where the same official table explicitly lists the
-- batch discount for this model.
INSERT INTO pricing_records(offering_id,price_type,amount,unit,valid_from,source_id,price_note)
SELECT o.id,v.price_type,v.amount,'per_1m_tokens','2026-09-30',s.id,v.note
FROM (SELECT 'Alibaba' provider,'INPUT' price_type,2.00 amount,'International deployment scope; USD per 1M tokens.' note
 UNION ALL SELECT 'Alibaba','OUTPUT',6.00,'International deployment scope; USD per 1M tokens.'
 UNION ALL SELECT 'Alibaba','BATCH_INPUT',1.00,'International; official Qwen3.8-Max table explicitly lists a 50% batch inference discount.'
 UNION ALL SELECT 'Alibaba','BATCH_OUTPUT',3.00,'International; derived as 50% of the listed $6 standard output rate.'
 UNION ALL SELECT 'Alibaba (China)','INPUT',1.65,'China (Beijing) deployment scope; USD per 1M tokens.'
 UNION ALL SELECT 'Alibaba (China)','OUTPUT',4.951,'China (Beijing) deployment scope; USD per 1M tokens.') v
JOIN provider_offerings o ON o.api_model_id='qwen3.8-max' JOIN providers p ON p.id=o.provider_id AND p.name=v.provider
JOIN sources s ON s.name='Alibaba Cloud Model Studio pricing';

-- Normalize any old per-class price rows to aggregator/official source types in
-- public output via source metadata. Current official prices now take precedence.
UPDATE provider_offerings SET last_verified_at='2026-09-30',fetched_at='2026-09-30'
WHERE id IN (SELECT offering_id FROM pricing_records WHERE source_id IN
 (SELECT id FROM sources WHERE name IN ('OpenAI API pricing','Google Gemini API pricing','xAI API pricing','MiniMax API pricing','Z.ai API pricing','Mistral API pricing','Alibaba Cloud Model Studio pricing')));

-- MiniMax explicitly advertises two months free on annual Token Plan billing.
-- Start/end dates are left unknown because the official page publishes neither.
INSERT OR IGNORE INTO offers(provider_id,plan_id,title,offer_type,terms_url,starts_at,ends_at,source_id,status,description,first_seen_at,last_verified_at,verification_note,promotion_current_amount,promotion_reference_amount,promotion_currency,promotion_unit,promotion_discount_percent,region_restrictions,conditions)
SELECT p.id,pl.id,'MiniMax Token Plan annual billing: two months free','SUBSCRIPTION_PROMOTION',
 'https://platform.minimax.io/subscribe/token-plan',NULL,NULL,s.id,'ACTIVE',
 'Official page explicitly labels annual billing as two months free. Token Plan Plus is listed at $20 monthly or $200 annually; the $200 annual plan and monthly reference are recorded in plans. Applies to the subscription, not the PAYG API route. Expiry not published.',
 '2026-09-30','2026-09-30','Official MiniMax pricing page; annual offer wording verified. Expiry unknown.',
 200,240,'USD','annual_subscription',16.6667,NULL,'New annual subscription purchase; token subscription quota and terms apply.'
FROM providers p JOIN plans pl ON pl.provider_id=p.id AND pl.name='Token Plan Plus'
JOIN sources s ON s.name='MiniMax Token Plan'
WHERE p.name='MiniMax Token Plan (minimax.io)';

-- Z.ai calls cached-input storage "Limited-time Free" but gives no expiry,
-- amount basis beyond the table heading, reference price, or region restrictions.
INSERT OR IGNORE INTO offers(provider_id,offering_id,title,offer_type,terms_url,starts_at,ends_at,source_id,status,description,first_seen_at,last_verified_at,verification_note,promotion_current_amount,promotion_currency,promotion_unit,region_restrictions,conditions)
SELECT p.id,o.id,'GLM-5.3 cached input storage: limited-time free','PROVIDER_EXPLICIT_PROMOTION',
 'https://docs.z.ai/guides/overview/pricing',NULL,NULL,s.id,'ACTIVE',
 'Z.ai pricing explicitly labels cached input storage as Limited-time Free. Reference price, expiry, region restrictions, and storage billing interval are not published on the pricing page.',
 '2026-09-30','2026-09-30','Explicit promotion wording on the official Z.ai pricing page; unknown terms remain unknown.',
 0,'USD','officially_published_unit_unspecified',NULL,'Applies to GLM-5.3 cached input storage only; verify current eligibility with Z.ai.'
FROM providers p JOIN provider_offerings o ON o.provider_id=p.id AND o.api_model_id='glm-5.3'
JOIN sources s ON s.name='Z.ai API pricing' WHERE p.name='Z.ai';

-- Observe and select the base tier in the existing fact pipeline. Higher
-- context tiers remain separate pricing_records; they are never flattened into
-- this single selected scalar fact.
INSERT OR IGNORE INTO data_observations(entity,field,source,source_url,source_id,value_json,priority,observed_at,accepted,evidence)
SELECT 'offering:'||pr.offering_id,
 CASE pr.price_type WHEN 'INPUT' THEN 'input_price' WHEN 'OUTPUT' THEN 'output_price'
  WHEN 'CACHE_READ' THEN 'cache_read_price' WHEN 'CACHE_WRITE' THEN 'cache_write_price'
  WHEN 'BATCH_INPUT' THEN 'batch_input_price' WHEN 'BATCH_OUTPUT' THEN 'batch_output_price' END,
 'official:'||lower(replace(replace(s.name,' API pricing',''),' ', '-')),s.url,s.id,
 CAST(pr.amount AS TEXT),8,'2026-09-30',1,COALESCE(pr.price_note,'Official provider pricing')
FROM pricing_records pr JOIN sources s ON s.id=pr.source_id
WHERE s.source_type='official_provider' AND pr.valid_from='2026-09-30'
 AND pr.context_threshold IS NULL;

INSERT OR REPLACE INTO selected_facts(entity,field,observation_id)
SELECT d.entity,d.field,d.id FROM data_observations d
WHERE d.source LIKE 'official:%' AND d.observed_at='2026-09-30'
 AND d.id=(SELECT MAX(x.id) FROM data_observations x WHERE x.entity=d.entity AND x.field=d.field AND x.source=d.source);

-- Keep conflicting aggregator values in the review queue; the official figure
-- is selected for display, while alternatives remain available in price history.
INSERT OR IGNORE INTO review_queue(id,entity,proposed_change,current_value,proposed_value,sources,evidence,confidence,reason,status,created_at)
SELECT 'official-price-'||pr.offering_id||'-'||pr.price_type,
 'offering:'||pr.offering_id,
 CASE pr.price_type WHEN 'INPUT' THEN 'input_price' WHEN 'OUTPUT' THEN 'output_price'
  WHEN 'CACHE_READ' THEN 'cache_read_price' WHEN 'CACHE_WRITE' THEN 'cache_write_price' END,
 CAST(old.amount AS TEXT),CAST(pr.amount AS TEXT),
 json_array(old_source.url,s.url),
 'Official source value takes precedence for public display; aggregator observation retained in history.',
 'HIGH','Official and aggregator pricing disagree; official source selected and aggregator evidence retained.',
 'PENDING','2026-09-30'
FROM pricing_records pr JOIN sources s ON s.id=pr.source_id
JOIN provider_offerings o ON o.id=pr.offering_id
JOIN pricing_records old ON old.offering_id=pr.offering_id AND old.price_type=pr.price_type
 AND old.valid_until='2026-09-30' AND old.id=(SELECT MAX(h.id) FROM pricing_records h WHERE h.offering_id=pr.offering_id AND h.price_type=pr.price_type AND h.valid_until='2026-09-30')
JOIN sources old_source ON old_source.id=old.source_id
WHERE s.source_type='official_provider' AND pr.valid_from='2026-09-30' AND pr.context_threshold IS NULL
 AND pr.price_type IN ('INPUT','OUTPUT','CACHE_READ','CACHE_WRITE','BATCH_INPUT','BATCH_OUTPUT')
 AND old.amount!=pr.amount;
