-- peso: 5
-- Primeiro pedido feito de madrugada (0h–4h).
SELECT count(*)
FROM orders
WHERE order_number = 1 AND order_hour_of_day BETWEEN 0 AND 4;
