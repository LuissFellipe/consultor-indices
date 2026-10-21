-- peso: 600
-- Tela "meus pedidos": os 10 pedidos mais recentes de um usuário.
SELECT order_id, order_number, order_dow, order_hour_of_day, days_since_prior_order
FROM orders
WHERE user_id = 183981
ORDER BY order_number DESC
LIMIT 10;
