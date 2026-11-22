-- PostgreSQL contract for a disposable test database. CSOL never runs DDL.
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
