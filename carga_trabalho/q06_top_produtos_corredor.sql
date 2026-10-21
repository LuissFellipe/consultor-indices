-- peso: 20
-- Os 20 produtos mais vendidos do corredor "energy granola bars".
SELECT p.product_id, p.product_name, count(*) AS vendas
FROM products p
JOIN order_products op ON op.product_id = p.product_id
WHERE p.aisle_id = 3
GROUP BY p.product_id, p.product_name
ORDER BY vendas DESC
LIMIT 20;
