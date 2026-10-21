-- peso: 150
-- Página do produto: taxa de recompra.
SELECT avg(reordered::int) AS taxa_recompra, count(*) AS vendas
FROM order_products
WHERE product_id = 1374;
