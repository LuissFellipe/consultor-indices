# consultor-indices

Dado um banco e uma carga de trabalho (as consultas e quantas vezes cada uma
roda), quais índices criar? O consultor testa candidatos como **índices
hipotéticos** (HypoPG: o planejador enxerga, o disco não) e escolhe por um
**algoritmo guloso sob orçamento de espaço**, no estilo do AutoAdmin da
Microsoft. Depois **prova**: cria os escolhidos de verdade e mede o tempo real
antes e depois.

Base: [Instacart Market Basket](https://www.kaggle.com/datasets/psparks/instacart-market-basket-analysis)
— 3,4 milhões de pedidos, 33,8 milhões de itens, 49.688 produtos.

## Resultado

Carga de 15 consultas ponderadas por frequência, Postgres 17, a partir do banco
só com chaves primárias:

| | Planejador (estimado) | Relógio (medido) |
|---|---|---|
| Custo da carga por hora | 10,7% do original | **170,0 s → 13,9 s (8,2%)** |
| Índices escolhidos | `orders(user_id)`, `order_products(product_id)` | criados em 0,4 s e 8,4 s |

- Consultas por usuário: ~50 ms → < 0,3 ms. Por produto: ~230 ms → ~2 ms.
- As cinco consultas que o consultor disse que **não** melhorariam (agregação
  sem filtro, filtro pouco seletivo, `LIKE` sem opclass, departamento com
  produtos demais) de fato não melhoraram — saber dizer "não crie" é metade do
  trabalho.
- 35 candidatos, 528 EXPLAINs, 0,3 s de busca.

### O que a medição mostrou e a estimativa não

- **A HypoPG superestima o tamanho em ~3×** (75,8 MB estimados × 26,7 MB
  reais; 749 × 227 MB). Desde o Postgres 13 o B-tree deduplica chaves
  repetidas, e a HypoPG não modela isso. O orçamento fica conservador demais.
- **O planejador subestima o ganho**, às vezes em uma ordem de grandeza (q07:
  ×1,9 estimado, ×10,1 real; q09: ×5,8 × ×185). A ordem dos ganhos está certa;
  a magnitude, não. Hipótese: `random_page_cost = 4` (padrão, pensado para
  disco giratório) com a base inteira em memória.

## Como funciona

```
carga_trabalho/*.sql  (uma consulta por arquivo, com "-- peso: N")
   │
   ├─ candidatos.py   EXPLAIN VERBOSE → colunas por papel (igualdade, intervalo,
   │                  junção, ordem) → índices de 1 a 3 colunas, igualdade na frente
   ├─ custo.py        HypoPG: reset → cria hipotéticos → EXPLAIN → custo; cache
   │                  por (consulta, índices das tabelas que ela lê)
   ├─ guloso.py       a cada rodada, o candidato de maior ganho/tamanho que cabe
   │                  no orçamento; ganho recalculado (índices interagem)
   └─ medir.py        EXPLAIN (ANALYZE, TIMING OFF), mediana de 3 com cache quente
```

As colunas saem do plano do próprio Postgres, não de um parser de SQL: o
planejador já resolveu alias, subconsulta e a que tabela cada condição
pertence.

## Rodar

```
docker compose up -d --build                     # Postgres 17 + HypoPG na porta 5433
uvx kaggle datasets download psparks/instacart-market-basket-analysis -p data/raw --unzip
docker compose exec -T postgres psql -U consultor -d instacart -f - < db/carga.sql   # ~6 min

uv run python -m consultor recomendar            # --orcamento-mb 1024 --limiar 0.01
uv run python -m consultor provar                # cria os índices e mede antes/depois
uv run python -m consultor limpar                # volta ao banco só com chaves primárias
```

O Kaggle precisa de token em `~/.kaggle/access_token`. A competição original
exige aceitar as regras no site; o espelho acima tem os mesmos arquivos
(contagens conferidas: 3.421.083 pedidos, 32.434.489 + 1.384.617 itens).

## Limites conhecidos

- **Guloso não desfaz escolha.** Se `(product_id)` entra primeiro,
  `(product_id, order_id)` depois ganha pouco e não entra, mesmo que sozinho
  fosse melhor que o primeiro.
- **Custo do planejador como função objetivo.** Herda os erros dele (ver
  acima). Calibrar `random_page_cost` antes de recomendar é o próximo passo.
- **Escrita não entra na conta.** Índice deixa `INSERT`/`UPDATE` mais caros; a
  carga aqui é só leitura.
- **Só B-tree.** `LIKE 'prefixo%'` pediria `text_pattern_ops`; busca textual
  pediria GIN/trigram.
