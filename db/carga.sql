-- Carga dos CSVs do Kaggle (montados em /dados dentro do contêiner).
--   docker compose exec -T postgres psql -U consultor -d instacart -f /dev/stdin < db/carga.sql
-- Idempotente: esvazia antes de carregar.

\set ON_ERROR_STOP on
\timing on

TRUNCATE order_products, orders, products, aisles, departments;

\copy departments FROM '/dados/departments.csv' WITH (FORMAT csv, HEADER true)
\copy aisles      FROM '/dados/aisles.csv'      WITH (FORMAT csv, HEADER true)
\copy products    FROM '/dados/products.csv'    WITH (FORMAT csv, HEADER true)
-- days_since_prior_order vem vazio no primeiro pedido de cada usuário: o
-- FORMAT csv lê campo vazio sem aspas como NULL, que é o certo aqui
\copy orders      FROM '/dados/orders.csv'      WITH (FORMAT csv, HEADER true)

-- Os dois arquivos de itens têm o mesmo formato e nenhuma coluna dizendo de
-- qual conjunto vêm: a origem entra pela tabela de passagem.
CREATE TEMP TABLE passagem (
    order_id integer, product_id integer, add_to_cart_order smallint, reordered boolean
);
\copy passagem FROM '/dados/order_products__prior.csv' WITH (FORMAT csv, HEADER true)
INSERT INTO order_products SELECT *, 'prior' FROM passagem;
TRUNCATE passagem;
\copy passagem FROM '/dados/order_products__train.csv' WITH (FORMAT csv, HEADER true)
INSERT INTO order_products SELECT *, 'train' FROM passagem;

-- Sem estatística o planejador chuta, e o consultor mede contra o chute.
VACUUM ANALYZE;

SELECT 'departments' AS tabela, count(*) FROM departments
UNION ALL SELECT 'aisles', count(*) FROM aisles
UNION ALL SELECT 'products', count(*) FROM products
UNION ALL SELECT 'orders', count(*) FROM orders
UNION ALL SELECT 'order_products', count(*) FROM order_products;
