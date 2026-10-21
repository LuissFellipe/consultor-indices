-- peso: 80
-- Como a cesta do usuário se divide entre departamentos.
SELECT d.department, count(*) AS itens
FROM orders o
JOIN order_products op ON op.order_id = o.order_id
JOIN products p ON p.product_id = op.product_id
JOIN departments d ON d.department_id = p.department_id
WHERE o.user_id = 183981
GROUP BY d.department
ORDER BY itens DESC;
