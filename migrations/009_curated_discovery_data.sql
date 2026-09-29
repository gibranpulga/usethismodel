-- Curated, source-backed discovery records verified 2026-09-29.
-- Vendor performance claims are stored as VENDOR_CLAIM, never benchmark truth.

INSERT OR IGNORE INTO sources(name,url,source_type,reliability) VALUES
 ('OpenRouter Free Models Router','https://openrouter.ai/openrouter/free/apps','official_provider','HIGH'),
 ('OpenRouter pricing and rate limits','https://openrouter.ai/pricing/','official_provider','HIGH'),
 ('OpenAI Batch API','https://platform.openai.com/docs/api-reference/batch/object','official_docs','HIGH'),
 ('Tripo H3.1 documentation','https://developers.tripo3d.ai/de/models/v3-1','official_docs','HIGH'),
 ('Tripo P1 documentation','https://developers.tripo3d.ai/en/models/p1','official_docs','HIGH'),
 ('Meshy 7.1 announcement','https://www.meshy.ai/blog/meshy-7-1-launch','official_announcement','HIGH'),
 ('Meshy API pricing','https://www.meshy.ai/api','official_provider','HIGH'),
 ('Hunyuan 3D 3.1 documentation','https://cloud.tencent.com/document/product/1823/130051','official_docs','HIGH'),
 ('Tencent Cloud 3D pricing','https://intl.cloud.tencent.com/document/product/1041/49204?lang=en&pg=','official_provider','HIGH'),
 ('Hunyuan3D 2.1 repository','https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1','official_metadata','HIGH'),
 ('Rodin Gen-2.5 API','https://docs.hyper3d.ai/en/api-specification/rodin-gen2-5','official_docs','HIGH'),
 ('TRELLIS.2 repository','https://github.com/microsoft/TRELLIS.2','official_metadata','HIGH'),
 ('SPAR3D repository','https://github.com/Stability-AI/stable-point-aware-3d','official_metadata','HIGH'),
 ('Sloyd API pricing','https://www.sloyd.ai/api/pricing','official_provider','HIGH'),
 ('Hi3D API pricing','https://docs.hi3d.ai/en/api/getting-started/pricing','official_provider','HIGH'),
 ('3D Arena paper','https://arxiv.org/abs/2506.18787','benchmark_publisher','HIGH');

INSERT OR IGNORE INTO labs(name,website_url) VALUES
 ('Tripo AI','https://www.tripo3d.ai/'),('Meshy','https://www.meshy.ai/'),
 ('Tencent Hunyuan','https://hunyuan.tencent.com/'),('Hyper3D','https://hyper3d.ai/'),
 ('Microsoft Research','https://www.microsoft.com/research/'),('Stability AI','https://stability.ai/'),
 ('Sloyd','https://www.sloyd.ai/'),('Hi3D','https://www.hi3d.ai/');

INSERT OR IGNORE INTO providers(name,website_url) VALUES
 ('Tripo API','https://platform.tripo3d.ai/'),('Meshy API','https://www.meshy.ai/api'),
 ('Tencent Cloud','https://cloud.tencent.com/'),('Hyper3D API','https://hyper3d.ai/'),
 ('Self-hosted','https://github.com/'),('Sloyd API','https://www.sloyd.ai/api'),
 ('Hi3D API','https://docs.hi3d.ai/');

INSERT OR IGNORE INTO models(canonical_name,vendor,modality,open_weights,lab_id,canonical_slug,status,released_at,release_date_kind,first_seen_at) VALUES
 ('Tripo H3.1','Tripo AI','3D generation',0,(SELECT id FROM labs WHERE name='Tripo AI'),'tripo/h3.1','ACTIVE','2026-02-11','official','2026-09-29'),
 ('Tripo P1','Tripo AI','3D generation',0,(SELECT id FROM labs WHERE name='Tripo AI'),'tripo/p1','ACTIVE','2026-03-11','official','2026-09-29'),
 ('Meshy 7.1','Meshy','3D generation',0,(SELECT id FROM labs WHERE name='Meshy'),'meshy/7.1','ACTIVE','2026-09-10','official','2026-09-29'),
 ('Hunyuan 3D 3.1','Tencent Hunyuan','3D generation',0,(SELECT id FROM labs WHERE name='Tencent Hunyuan'),'tencent/hy-3d-3.1','ACTIVE',NULL,'unverified','2026-09-29'),
 ('Hunyuan3D 2.1','Tencent Hunyuan','3D generation',1,(SELECT id FROM labs WHERE name='Tencent Hunyuan'),'tencent/hunyuan3d-2.1','ACTIVE',NULL,'unverified','2026-09-29'),
 ('Rodin Gen-2.5','Hyper3D','3D generation',0,(SELECT id FROM labs WHERE name='Hyper3D'),'hyper3d/rodin-gen-2.5','ACTIVE',NULL,'unverified','2026-09-29'),
 ('TRELLIS.2-4B','Microsoft Research','3D generation',1,(SELECT id FROM labs WHERE name='Microsoft Research'),'microsoft/trellis.2-4b','ACTIVE',NULL,'unverified','2026-09-29'),
 ('SPAR3D','Stability AI','3D generation',1,(SELECT id FROM labs WHERE name='Stability AI'),'stability-ai/spar3d','ACTIVE',NULL,'unverified','2026-09-29'),
 ('Sloyd','Sloyd','3D generation',0,(SELECT id FROM labs WHERE name='Sloyd'),'sloyd/api','ACTIVE',NULL,'unverified','2026-09-29'),
 ('Hi3D v3.0','Hi3D','3D generation',0,(SELECT id FROM labs WHERE name='Hi3D'),'hi3d/v3.0','ACTIVE',NULL,'unverified','2026-09-29'),
 ('OpenRouter Free Models Router','OpenRouter','multimodal LLM',0,NULL,'openrouter/free','ACTIVE','2026-02-01','official','2026-09-29');

INSERT OR IGNORE INTO provider_offerings(model_id,provider_id,api_model_id,tool_support,structured_output_support,free_status,rate_limit_note,caveat,source_id,fetched_at,first_seen_at,privacy_caveat,commercial_use) VALUES
 ((SELECT id FROM models WHERE canonical_slug='tripo/h3.1'),(SELECT id FROM providers WHERE name='Tripo API'),'v3.1-20260211','NO','UNKNOWN','PAID',NULL,'Generation times are vendor estimates.',(SELECT id FROM sources WHERE name='Tripo H3.1 documentation'),'2026-09-29','2026-09-29',NULL,'YES'),
 ((SELECT id FROM models WHERE canonical_slug='tripo/p1'),(SELECT id FROM providers WHERE name='Tripo API'),'P1-20260311','NO','UNKNOWN','PAID',NULL,'Generation times are vendor estimates.',(SELECT id FROM sources WHERE name='Tripo P1 documentation'),'2026-09-29','2026-09-29',NULL,'YES'),
 ((SELECT id FROM models WHERE canonical_slug='meshy/7.1'),(SELECT id FROM providers WHERE name='Meshy API'),'Meshy-7','NO','UNKNOWN','PAID',NULL,'Service UI is Meshy 7.1; API family remains labeled Meshy-7. Quality comparisons are vendor claims.',(SELECT id FROM sources WHERE name='Meshy 7.1 announcement'),'2026-09-29','2026-09-29',NULL,'YES'),
 ((SELECT id FROM models WHERE canonical_slug='tencent/hy-3d-3.1'),(SELECT id FROM providers WHERE name='Tencent Cloud'),'hy-3d-3.1','NO','UNKNOWN','PAID',NULL,'3.1 endpoint is geometry-only; texture, topology and rigging are separate service stages.',(SELECT id FROM sources WHERE name='Hunyuan 3D 3.1 documentation'),'2026-09-29','2026-09-29',NULL,'YES'),
 ((SELECT id FROM models WHERE canonical_slug='tencent/hunyuan3d-2.1'),(SELECT id FROM providers WHERE name='Self-hosted'),'tencent/Hunyuan3D-2.1','NO','UNKNOWN','UNKNOWN',NULL,'No official hosted API price. Open weights use the Tencent Hunyuan Non-Commercial License.',(SELECT id FROM sources WHERE name='Hunyuan3D 2.1 repository'),'2026-09-29','2026-09-29',NULL,'NO'),
 ((SELECT id FROM models WHERE canonical_slug='hyper3d/rodin-gen-2.5'),(SELECT id FROM providers WHERE name='Hyper3D API'),'Rodin Gen-2.5','NO','UNKNOWN','PAID',NULL,'Official pages conflict between a 0.5-credit base and “from 1 credit”; check final task cost before generation.',(SELECT id FROM sources WHERE name='Rodin Gen-2.5 API'),'2026-09-29','2026-09-29',NULL,'CONDITIONAL'),
 ((SELECT id FROM models WHERE canonical_slug='microsoft/trellis.2-4b'),(SELECT id FROM providers WHERE name='Self-hosted'),'microsoft/TRELLIS.2-4B','NO','UNKNOWN','UNKNOWN',NULL,'No official hosted API. Requires Linux, NVIDIA GPU and roughly 24GB+ VRAM; review NVIDIA dependency terms.',(SELECT id FROM sources WHERE name='TRELLIS.2 repository'),'2026-09-29','2026-09-29',NULL,'CONDITIONAL'),
 ((SELECT id FROM models WHERE canonical_slug='stability-ai/spar3d'),(SELECT id FROM providers WHERE name='Self-hosted'),'stability-ai/stable-point-aware-3d','NO','UNKNOWN','UNKNOWN',NULL,'Community License terms vary with organization revenue.',(SELECT id FROM sources WHERE name='SPAR3D repository'),'2026-09-29','2026-09-29',NULL,'CONDITIONAL'),
 ((SELECT id FROM models WHERE canonical_slug='sloyd/api'),(SELECT id FROM providers WHERE name='Sloyd API'),'sloyd-generation-v1','NO','UNKNOWN','PAID',NULL,NULL,(SELECT id FROM sources WHERE name='Sloyd API pricing'),'2026-09-29','2026-09-29',NULL,'YES'),
 ((SELECT id FROM models WHERE canonical_slug='hi3d/v3.0'),(SELECT id FROM providers WHERE name='Hi3D API'),'hi3dv3.0','NO','UNKNOWN','PAID',NULL,NULL,(SELECT id FROM sources WHERE name='Hi3D API pricing'),'2026-09-29','2026-09-29',NULL,'YES');

INSERT OR IGNORE INTO provider_offerings(model_id,provider_id,api_model_id,context_limit,max_output_tokens,tool_support,structured_output_support,free_status,rate_limit_note,caveat,source_id,fetched_at,first_seen_at,privacy_caveat,commercial_use) VALUES
 ((SELECT id FROM models WHERE canonical_slug='openrouter/free'),(SELECT id FROM providers WHERE name='OpenRouter'),'openrouter/free',200000,NULL,'YES','YES','FREE','Free plan: 50 requests/day. Capacity and selected underlying model can change.','The router chooses among currently available free models and filters for requested capabilities.',(SELECT id FROM sources WHERE name='OpenRouter Free Models Router'),'2026-09-29','2026-09-29','The underlying provider varies. The free plan does not include data-policy-based routing; review the selected provider policy before sensitive use.','CONDITIONAL');

INSERT INTO pricing_records(offering_id,price_type,amount,unit,valid_from,source_id,price_note) VALUES
 ((SELECT id FROM provider_offerings WHERE api_model_id='hy-3d-3.1'),'THREE_D_GENERATION',0.32,'per_3d_generation','2026-09-29',(SELECT id FROM sources WHERE name='Tencent Cloud 3D pricing'),'Geometry plus texture MPS run; the 3.1 generation endpoint itself is geometry-only and workflows may use separate stages.'),
 ((SELECT id FROM provider_offerings WHERE api_model_id='sloyd-generation-v1'),'THREE_D_GENERATION',0.133333,'per_3d_generation','2026-09-29',(SELECT id FROM sources WHERE name='Sloyd API pricing'),'Base geometry: 10 credits at the published API rate of 75 credits/USD; options add credits.'),
 ((SELECT id FROM provider_offerings WHERE api_model_id='hi3dv3.0'),'THREE_D_GENERATION',2.10,'per_3d_generation','2026-09-29',(SELECT id FROM sources WHERE name='Hi3D API pricing'),'Quality tier including PBR; master tier is separately priced.'),
 ((SELECT id FROM provider_offerings WHERE api_model_id='openrouter/free'),'INPUT',0,'per_1m_tokens','2026-09-29',(SELECT id FROM sources WHERE name='OpenRouter Free Models Router'),'Exact $0 router route.'),
 ((SELECT id FROM provider_offerings WHERE api_model_id='openrouter/free'),'OUTPUT',0,'per_1m_tokens','2026-09-29',(SELECT id FROM sources WHERE name='OpenRouter Free Models Router'),'Exact $0 router route.');

INSERT OR REPLACE INTO model_media_features(model_id,text_to_3d,image_to_3d,multi_view,texturing,rigging,topology_low_poly,output_formats,generation_time_note,commercial_use_note,evidence_kind,source_id,last_verified_at) VALUES
 ((SELECT id FROM models WHERE canonical_slug='tripo/h3.1'),'YES','YES','YES','YES','YES','YES','GLTF, FBX, USDZ, OBJ, STL, 3MF','Vendor estimate: about 40s geometry / 120s textured.','Paid outputs support commercial use; free plan is non-commercial.','VENDOR_CLAIM',(SELECT id FROM sources WHERE name='Tripo H3.1 documentation'),'2026-09-29'),
 ((SELECT id FROM models WHERE canonical_slug='tripo/p1'),'YES','YES','YES','YES','YES','YES','GLTF, FBX, USDZ, OBJ, STL, 3MF','Vendor estimate: about 10s geometry / 60s textured.','Paid outputs support commercial use; free plan is non-commercial.','VENDOR_CLAIM',(SELECT id FROM sources WHERE name='Tripo P1 documentation'),'2026-09-29'),
 ((SELECT id FROM models WHERE canonical_slug='meshy/7.1'),'YES','YES','YES','YES','YES','YES','GLB, FBX, OBJ, STL, USDZ, 3MF, BLEND','Vendor documentation: standard generation roughly 1–2 minutes; T2 topology about 2s.','Paid outputs private/commercial; free outputs CC BY 4.0.','VENDOR_CLAIM',(SELECT id FROM sources WHERE name='Meshy 7.1 announcement'),'2026-09-29'),
 ((SELECT id FROM models WHERE canonical_slug='tencent/hy-3d-3.1'),'YES','YES','YES','YES','YES','YES','FBX from motion stage; service-stage formats vary','Not independently verified.','Cloud service terms apply.','VENDOR_CLAIM',(SELECT id FROM sources WHERE name='Hunyuan 3D 3.1 documentation'),'2026-09-29'),
 ((SELECT id FROM models WHERE canonical_slug='tencent/hunyuan3d-2.1'),'NO','YES','YES','YES','NO','UNKNOWN','GLB, OBJ',NULL,'Tencent Hunyuan Non-Commercial License.','VERIFIED',(SELECT id FROM sources WHERE name='Hunyuan3D 2.1 repository'),'2026-09-29'),
 ((SELECT id FROM models WHERE canonical_slug='hyper3d/rodin-gen-2.5'),'YES','YES','YES','YES','NO','YES','GLB, USDZ, FBX, OBJ, STL','Vendor claim: about 4s base geometry / 5s textured; larger jobs take longer.','Commercial use depends on plan and terms.','VENDOR_CLAIM',(SELECT id FROM sources WHERE name='Rodin Gen-2.5 API'),'2026-09-29'),
 ((SELECT id FROM models WHERE canonical_slug='microsoft/trellis.2-4b'),'NO','YES','NO','YES','NO','YES','GLB','Vendor timings on H100: roughly 3s at 512³, 17s at 1024³, 60s at 1536³.','MIT model/code; review NVIDIA dependency licenses.','VENDOR_CLAIM',(SELECT id FROM sources WHERE name='TRELLIS.2 repository'),'2026-09-29'),
 ((SELECT id FROM models WHERE canonical_slug='stability-ai/spar3d'),'NO','YES','NO','YES','NO','YES','GLB','Vendor claim: about 0.7s/object.','Community License; free commercial use below stated revenue threshold with registration.','VENDOR_CLAIM',(SELECT id FROM sources WHERE name='SPAR3D repository'),'2026-09-29'),
 ((SELECT id FROM models WHERE canonical_slug='sloyd/api'),'YES','YES','YES','YES','YES','YES','GLB, OBJ, FBX',NULL,'Paid plans/API support commercial use.','VERIFIED',(SELECT id FROM sources WHERE name='Sloyd API pricing'),'2026-09-29'),
 ((SELECT id FROM models WHERE canonical_slug='hi3d/v3.0'),'NO','YES','YES','YES','NO','UNKNOWN','GLB, OBJ, STL, 3MF',NULL,'Paid outputs private/commercial; free outputs CC BY 4.0.','VERIFIED',(SELECT id FROM sources WHERE name='Hi3D API pricing'),'2026-09-29');

INSERT OR IGNORE INTO offers(provider_id,offering_id,title,offer_type,terms_url,starts_at,ends_at,source_id,status,description,first_seen_at,last_verified_at,verification_note,privacy_caveat) VALUES
 ((SELECT id FROM providers WHERE name='OpenRouter'),(SELECT id FROM provider_offerings WHERE api_model_id='openrouter/free'),'OpenRouter Free Models Router','$0_ROUTE','https://openrouter.ai/openrouter/free/apps','2026-02-01',NULL,(SELECT id FROM sources WHERE name='OpenRouter Free Models Router'),'ACTIVE','$0 input and output on the exact openrouter/free route; the underlying model/provider can vary.','2026-09-29','2026-09-29','Verified against the official route and pricing pages.','Free plan has no data-policy-based routing; underlying provider policies vary.'),
 ((SELECT id FROM providers WHERE name='OpenAI'),NULL,'OpenAI Batch API — 50% discount','BATCH_DISCOUNT','https://platform.openai.com/docs/api-reference/batch/object',NULL,NULL,(SELECT id FROM sources WHERE name='OpenAI Batch API'),'ACTIVE','Asynchronous batches complete within 24 hours for a documented 50% discount on supported endpoints.','2026-09-29','2026-09-29','Official API documentation; this is a batch execution discount, not a normal-price estimate.',NULL);

INSERT OR IGNORE INTO benchmarks(name,version,category,description,source_id) VALUES
 ('3D Arena','2025 paper','3D generation','Pairwise human-preference benchmark. Presentation format materially affects Elo; do not interpret it as topology or production-readiness quality.',(SELECT id FROM sources WHERE name='3D Arena paper'));
