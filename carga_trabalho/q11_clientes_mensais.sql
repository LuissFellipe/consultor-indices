-- peso: 10
-- Clientes que compram de 30 em 30 dias aos domingos (campanha de e-mail).
SELECT count(DISTINCT user_id)
FROM orders
WHERE days_since_prior_order = 30 AND order_dow = 0;
