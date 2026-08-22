CREATE SCHEMA IF NOT EXISTS talk2data;

CREATE TABLE IF NOT EXISTS talk2data.metric_facts (
    fact_date date NOT NULL,
    period_end date NOT NULL,
    metric_id text NOT NULL,
    amount double precision,
    numerator double precision,
    denominator double precision,
    plan_id text,
    market_id text,
    region_id text,
    channel_id text,
    store_id text,
    cell_site_id text,
    hour_id text,
    technology_id text,
    CONSTRAINT metric_value_shape CHECK (
        (amount IS NOT NULL AND numerator IS NULL AND denominator IS NULL)
        OR
        (amount IS NULL AND numerator IS NOT NULL AND denominator IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS metric_facts_metric_date_idx
    ON talk2data.metric_facts(metric_id, fact_date);

TRUNCATE TABLE talk2data.metric_facts;

INSERT INTO talk2data.metric_facts (
    fact_date, period_end, metric_id, amount, numerator, denominator,
    plan_id, market_id, region_id, channel_id, store_id,
    cell_site_id, hour_id, technology_id
) VALUES
    ('2026-06-01', '2026-06-30', 'POSTPAID_CHURN', NULL, 120, 5000, 'STARTER', 'NORTHEAST_MARKET', 'NORTHEAST', 'RETAIL', NULL, NULL, NULL, NULL),
    ('2026-06-01', '2026-06-30', 'POSTPAID_CHURN', NULL, 92, 5000, 'UNLIMITED', 'NORTHEAST_MARKET', 'NORTHEAST', 'RETAIL', NULL, NULL, NULL, NULL),
    ('2026-06-01', '2026-06-30', 'POSTPAID_CHURN', NULL, 67, 5000, 'PREMIUM', 'NORTHEAST_MARKET', 'NORTHEAST', 'RETAIL', NULL, NULL, NULL, NULL),
    ('2026-07-01', '2026-07-31', 'POSTPAID_CHURN', NULL, 117, 5000, 'STARTER', 'NORTHEAST_MARKET', 'NORTHEAST', 'RETAIL', NULL, NULL, NULL, NULL),
    ('2026-07-01', '2026-07-31', 'POSTPAID_CHURN', NULL, 89, 5000, 'UNLIMITED', 'NORTHEAST_MARKET', 'NORTHEAST', 'RETAIL', NULL, NULL, NULL, NULL),
    ('2026-07-01', '2026-07-31', 'POSTPAID_CHURN', NULL, 64, 5000, 'PREMIUM', 'NORTHEAST_MARKET', 'NORTHEAST', 'RETAIL', NULL, NULL, NULL, NULL),
    ('2026-06-01', '2026-06-30', 'MOBILE_ACTIVATIONS', 6113, NULL, NULL, NULL, 'NORTHEAST_MARKET', 'NORTHEAST', 'RETAIL', 'NORTHEAST_STORE_1', NULL, NULL, NULL),
    ('2026-06-01', '2026-06-30', 'MOBILE_ACTIVATIONS', 4279, NULL, NULL, NULL, 'NORTHEAST_MARKET', 'NORTHEAST', 'DIGITAL', 'NORTHEAST_STORE_2', NULL, NULL, NULL),
    ('2026-06-01', '2026-06-30', 'MOBILE_ACTIVATIONS', 1834, NULL, NULL, NULL, 'NORTHEAST_MARKET', 'NORTHEAST', 'CARE', 'NORTHEAST_STORE_3', NULL, NULL, NULL),
    ('2026-07-01', '2026-07-31', 'MOBILE_ACTIVATIONS', 6178, NULL, NULL, NULL, 'NORTHEAST_MARKET', 'NORTHEAST', 'RETAIL', 'NORTHEAST_STORE_1', NULL, NULL, NULL),
    ('2026-07-01', '2026-07-31', 'MOBILE_ACTIVATIONS', 4324, NULL, NULL, NULL, 'NORTHEAST_MARKET', 'NORTHEAST', 'DIGITAL', 'NORTHEAST_STORE_2', NULL, NULL, NULL),
    ('2026-07-01', '2026-07-31', 'MOBILE_ACTIVATIONS', 1853, NULL, NULL, NULL, 'NORTHEAST_MARKET', 'NORTHEAST', 'CARE', 'NORTHEAST_STORE_3', NULL, NULL, NULL),
    ('2026-07-31', '2026-07-31', 'NETWORK_CONGESTION', NULL, 160, 2000, NULL, 'NY_METRO', 'NORTHEAST', NULL, NULL, 'NYC_SITE_1', 'EVENING', 'LTE'),
    ('2026-07-31', '2026-07-31', 'NETWORK_CONGESTION', NULL, 220, 2000, NULL, 'NY_METRO', 'NORTHEAST', NULL, NULL, 'NYC_SITE_2', 'EVENING', 'FIVE_G');

GRANT USAGE ON SCHEMA talk2data TO talk2data;
GRANT SELECT ON talk2data.metric_facts TO talk2data;
