-- Cover the exact route/harness/workflow predicates used in compatibility queries.
CREATE INDEX idx_route_compatibility_harness_offering ON route_compatibility_evidence(harness_id, offering_id);
CREATE INDEX idx_workflow_harness_integration_state ON workflow_harness_compatibility(harness_id, integration_id, state);
CREATE INDEX idx_pricing_current_route_class ON pricing_records(offering_id, price_type, context_threshold, valid_from DESC) WHERE valid_until IS NULL;
