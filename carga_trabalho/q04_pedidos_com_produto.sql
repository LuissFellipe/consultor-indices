-- peso: 120
-- Quantos pedidos levaram um produto de nicho (abacate orgânico em saco).
SELECT count(DISTINCT order_id)
FROM order_products
WHERE product_id = 1374;
