-- peso: 300
-- Busca por prefixo do nome. B-tree comum não serve para LIKE com collation
-- não-C; é um caso em que o consultor deve falhar sem opclass especial.
SELECT product_id, product_name
FROM products
WHERE product_name LIKE 'Organic Hass%'
ORDER BY product_name
LIMIT 20;
