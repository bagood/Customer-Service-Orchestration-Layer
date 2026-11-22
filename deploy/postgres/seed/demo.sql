INSERT INTO csol.customers (customer_id, balance)
VALUES ('demo-customer', 20)
ON CONFLICT (customer_id) DO NOTHING;

INSERT INTO csol.packages (package_id, name, benefits, quota_gb, price)
VALUES ('demo-package', 'Demo 5 GB', 'CSOL demo data', 5, 50)
ON CONFLICT (package_id) DO NOTHING;
