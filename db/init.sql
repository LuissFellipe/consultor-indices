-- Schema do Instacart Market Basket com só as chaves primárias.
-- Nenhum índice secundário de propósito: achá-los é o trabalho do consultor.
-- Chave estrangeira entra porque documenta o modelo, e no Postgres ela não cria
-- índice no lado que referencia.

CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
CREATE EXTENSION IF NOT EXISTS hypopg;

CREATE TABLE departments (
    department_id integer PRIMARY KEY,
    department    text NOT NULL
);

CREATE TABLE aisles (
    aisle_id integer PRIMARY KEY,
    aisle    text NOT NULL
);

CREATE TABLE products (
    product_id    integer PRIMARY KEY,
    product_name  text NOT NULL,
    aisle_id      integer NOT NULL REFERENCES aisles,
    department_id integer NOT NULL REFERENCES departments
);

-- eval_set: 'prior' (histórico), 'train' (último pedido, com itens em
-- order_products_train) e 'test' (último pedido, sem itens).
CREATE TABLE orders (
    order_id               integer PRIMARY KEY,
    user_id                integer NOT NULL,
    eval_set               text NOT NULL,
    order_number           smallint NOT NULL,
    order_dow              smallint NOT NULL,
    order_hour_of_day      smallint NOT NULL,
    days_since_prior_order real
);

-- No CSV são dois arquivos (prior e train) com o mesmo formato. Aqui viram uma
-- tabela só, com a origem numa coluna: a maioria das perguntas quer as duas.
CREATE TABLE order_products (
    order_id          integer NOT NULL REFERENCES orders,
    product_id        integer NOT NULL REFERENCES products,
    add_to_cart_order smallint NOT NULL,
    reordered         boolean NOT NULL,
    eval_set          text NOT NULL,
    PRIMARY KEY (order_id, add_to_cart_order)
);
