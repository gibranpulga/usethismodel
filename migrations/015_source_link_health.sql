-- The locally inspected Hermes commit is no longer addressable in the public
-- GitHub repository. Keep the exact inspected revision in the evidence note,
-- but point the public source link at the maintained upstream repository.
UPDATE sources
SET url='https://github.com/NousResearch/hermes-agent', fetched_at='2026-09-30'
WHERE name='Hermes installed version inspection';
