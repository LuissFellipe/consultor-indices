-- peso: 400
-- "Pedir de novo": itens do último pedido do usuário, com o nome do produto.
SELECT p.product_name, op.add_to_cart_order
FROM orders o
JOIN order_products op ON op.order_id = o.order_id
JOIN products p ON p.product_id = op.product_id
WHERE o.user_id = 9973
  AND o.order_number = (SELECT max(order_number) FROM orders WHERE user_id = 9973 AND eval_set = 'prior')
ORDER BY op.add_to_cart_order;
