-- peso: 30
-- "Quem comprou abacate orgânico também levou": produtos nos mesmos pedidos.
SELECT op2.product_id, count(*) AS juntos
FROM order_products op1
JOIN order_products op2 ON op2.order_id = op1.order_id AND op2.product_id <> op1.product_id
WHERE op1.product_id = 1374
GROUP BY op2.product_id
ORDER BY juntos DESC
LIMIT 10;
