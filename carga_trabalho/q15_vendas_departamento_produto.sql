-- peso: 15
-- Recompra média dos produtos congelados mais vendidos.
SELECT p.product_name, count(*) AS vendas, avg(op.reordered::int) AS recompra
FROM products p
JOIN order_products op ON op.product_id = p.product_id
WHERE p.department_id = 1
GROUP BY p.product_name
ORDER BY vendas DESC
LIMIT 10;
