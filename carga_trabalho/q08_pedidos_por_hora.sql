-- peso: 2
-- Controle: distribuição de pedidos por dia e hora. Lê a tabela inteira;
-- índice não ajuda agregação sem filtro.
SELECT order_dow, order_hour_of_day, count(*)
FROM orders
GROUP BY order_dow, order_hour_of_day
ORDER BY order_dow, order_hour_of_day;
