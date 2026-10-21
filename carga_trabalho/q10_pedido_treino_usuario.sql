-- peso: 100
-- O pedido do conjunto de treino de um usuário (o "próximo pedido" a prever).
SELECT order_id, order_dow, order_hour_of_day
FROM orders
WHERE user_id = 9973 AND eval_set = 'train';
