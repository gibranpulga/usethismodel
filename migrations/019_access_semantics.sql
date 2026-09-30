-- Keep marginal token price separate from the access contract.
ALTER TABLE provider_offerings ADD COLUMN access_semantics TEXT NOT NULL DEFAULT 'UNKNOWN'
  CHECK (access_semantics IN ('FREE_API','FREE_TIER','INCLUDED_WITH_SUBSCRIPTION',
    'PAID_API','PROMOTIONAL_FREE','TRIAL_CREDIT','UNKNOWN'));
ALTER TABLE provider_offerings ADD COLUMN access_requirement TEXT;

UPDATE provider_offerings
SET access_semantics='INCLUDED_WITH_SUBSCRIPTION',
    access_requirement=(SELECT p.name FROM providers p WHERE p.id=provider_offerings.provider_id)
WHERE free_status='FREE' AND EXISTS (
  SELECT 1 FROM providers p WHERE p.id=provider_offerings.provider_id
    AND (lower(p.name) LIKE '%token plan%' OR lower(p.name) LIKE '%coding plan%'
         OR lower(p.name) LIKE '%gitlab duo%' OR lower(p.name) LIKE '%opencode go%')
);
UPDATE provider_offerings SET access_semantics='FREE_API'
WHERE free_status='FREE' AND access_semantics='UNKNOWN';
