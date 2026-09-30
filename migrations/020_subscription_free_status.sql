-- Zero incremental token pricing does not make a paid-plan route publicly free.
UPDATE provider_offerings SET free_status='PAID'
WHERE access_semantics='INCLUDED_WITH_SUBSCRIPTION' AND free_status='FREE';
