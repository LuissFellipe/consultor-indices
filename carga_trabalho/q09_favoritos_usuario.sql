-- peso: 200
-- Os produtos que o usuário mais recompra (base de uma recomendação).
SELECT op.product_id, count(*) AS vezes
FROM orders o
JOIN order_products op ON op.order_id = o.order_id
WHERE o.user_id = 183981 AND op.reordered
GROUP BY op.product_id
ORDER BY vezes DESC
LIMIT 15;
