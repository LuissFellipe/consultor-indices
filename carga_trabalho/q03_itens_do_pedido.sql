-- peso: 800
-- Controle: itens de um pedido. A chave primária (order_id, add_to_cart_order)
-- já resolve; um consultor que sugira índice aqui está errado.
SELECT product_id, add_to_cart_order, reordered
FROM order_products
WHERE order_id = 2539329
ORDER BY add_to_cart_order;
