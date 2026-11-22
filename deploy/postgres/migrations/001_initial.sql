-- Initial CSOL schema. Keep the integration fixture in sync with the schema contract.
CREATE SCHEMA csol;
CREATE TABLE csol.customers (
    customer_id text PRIMARY KEY,
    name text,
    balance bigint NOT NULL CHECK (balance >= 0)
);
CREATE TABLE csol.packages (
    package_id text PRIMARY KEY,
    name text NOT NULL,
    benefits text NOT NULL,
    quota_gb integer NOT NULL CHECK (quota_gb >= 0),
    price bigint NOT NULL CHECK (price > 0)
);
CREATE TABLE csol.operations (
    operation_id text PRIMARY KEY,
    customer_id text NOT NULL REFERENCES csol.customers,
    kind text NOT NULL,
    result jsonb NOT NULL
);

GRANT USAGE ON SCHEMA csol TO csol_app;
GRANT SELECT ON csol.customers, csol.packages, csol.operations TO csol_app;
GRANT UPDATE (name, balance) ON csol.customers TO csol_app;
GRANT INSERT ON csol.operations TO csol_app;
-- PostgreSQL requires UPDATE on at least one column for SELECT ... FOR SHARE.
GRANT UPDATE (package_id) ON csol.packages TO csol_app;
