-- Aggregate, privacy-preserving product telemetry. No IP addresses, cookies,
-- search text, prompt contents, or user identifiers are stored.
CREATE TABLE analytics_daily (
  day TEXT NOT NULL,
  event TEXT NOT NULL,
  dimension TEXT NOT NULL DEFAULT '',
  count INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY(day,event,dimension)
);

