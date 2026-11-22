-- Seed a new disposable wallet for one full Hermes acceptance run.
BEGIN;
INSERT INTO csol.customers(customer_id, balance) VALUES ('demo-wallet', 20);
INSERT INTO csol.packages(package_id, name, benefits, quota_gb, price)
VALUES ('demo-package', 'Video 5', 'streaming', 5, 50);
COMMIT;
