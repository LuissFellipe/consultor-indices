# consultor-indices

Dado um banco e uma carga de trabalho (as consultas e quantas vezes cada uma
roda), quais índices criar? O consultor testa candidatos como **índices
hipotéticos** (HypoPG: o planejador enxerga, o disco não) e escolhe por um
**algoritmo guloso sob orçamento de espaço**, no estilo do AutoAdmin da
Microsoft. Depois **prova**: cria os escolhidos de verdade e mede o tempo real
antes e depois.

**Página com os gráficos:** https://luissfellipe.github.io/consultor-indices/

Base: [Instacart Market Basket](https://www.kaggle.com/datasets/psparks/instacart-market-basket-analysis)
— 3,4 milhões de pedidos, 33,8 milhões de itens, 49.688 produtos.

## Que perguntas ele responde

Dadas as consultas que o sistema roda e quantas vezes por hora cada uma roda:

| Pergunta | Resposta nesta base |
|---|---|
| Que índices eu crio? | `orders(user_id)` e `order_products(product_id)`, entre 35 candidatos |
| Em que ordem, e quanto cada um vale? | 1º `orders(user_id)`: custo da carga cai para 63,3%; 2º `order_products(product_id)`: 10,9%. O primeiro ganha menos, mas ocupa 10× menos espaço (critério: ganho por byte) |
| Qual consulta cada índice atende? | `orders(user_id)`: q01, q02, q09, q10, q13 · `order_products(product_id)`: q04, q05, q06, q07 |
| Onde nenhum índice ajuda? | q03, q08, q11, q12, q14, q15 — chave primária já resolve, leitura da tabela inteira, filtro pouco seletivo ou `LIKE` sem o índice certo |
| Quanto espaço vou gastar? | 253,8 MB reais (a HypoPG estimou 824,8 MB). Orçamento configurável com `--orcamento-mb` |
| O ganho previsto se confirma? | Sim, e maior: 170,0 s → 13,9 s de consulta por hora (8,2% medido × 10,9% estimado) |
| Algum índice piora alguma consulta? | Com os recomendados, não. O `provar` marca REGRESSÃO quando acontece |
| Posso confiar na estimativa do planejador? | Para a carga inteira, com `random_page_cost = 2`. Com valor menor, não: ele recomenda um terceiro índice e a carga medida dobra |

Não responde: o custo do índice na escrita (`INSERT`/`UPDATE`), índices que
não sejam B-tree, e qual seria o conjunto ótimo — o guloso acha um bom, não
necessariamente o melhor.

## Resultado

Carga de 15 consultas ponderadas por frequência, Postgres 17, a partir do banco
só com chaves primárias:

| | Planejador (estimado) | Relógio (medido) |
|---|---|---|
| Custo da carga por hora | 10,9% do original¹ | **170,0 s → 13,9 s (8,2%)** |
| Índices escolhidos | `orders(user_id)`, `order_products(product_id)` | criados em 0,4 s e 8,4 s |

¹ Entre 10,7% e 10,9% conforme a rodada: o `ANALYZE` amostra a tabela, e as
estatísticas mudam um pouco a cada vez. Os índices escolhidos não mudam.

- Consultas por usuário: ~50 ms → < 0,3 ms. Por produto: ~230 ms → ~2 ms.
- As seis consultas em que o consultor previu ganho nenhum (chave primária já
  resolve, agregação sem filtro, filtros pouco seletivos, `LIKE` sem opclass
  com collation `en_US.utf8`, departamento com produtos demais) de fato não
  melhoraram — saber dizer "não crie" é metade do trabalho.
- 35 candidatos, 528 EXPLAINs, 0,3 s de busca.

### O que a medição mostrou e a estimativa não

- **A HypoPG estima o tamanho sem deduplicação.** 75,8 MB estimados × 26,7 MB
  reais; 749 × 227 MB. Criados com `deduplicate_items = off`, os mesmos
  índices ocupam 73 e 725 MB — a 4% da estimativa. O B-tree deduplica chave
  repetida desde o Postgres 13, e a HypoPG não modela isso. O orçamento fica
  conservador demais, mas o **custo** quase não muda: o erro de estimativa
  com o índice hipotético e com o real é o mesmo (ver calibração).
- **O planejador subestima o ganho** no padrão (q07: ×1,9 estimado, ×10,1
  real; q09: ×5,8 × ×185). A ordem dos ganhos está certa; a magnitude, não.

### Calibração do `random_page_cost`

`uv run python -m consultor calibrar` refaz a recomendação para cada valor,
cria o conjunto recomendado e mede (resultado em `resultados/calibracao.json`):

| `random_page_cost` | Recomendados | Carga estimada | Carga medida |
|---|---|---|---|
| 4 (padrão) | 2 índices | 10,9% | 7,3% |
| **2** | 2 índices | **7,8%** | **7,5%** |
| 1,5 | 3 índices | 6,8% | **15,7%** ⚠ |
| 1,1 | 3 índices | 5,8% | **15,8%** ⚠ |
| 1 | 3 índices | 5,6% | **15,6%** ⚠ |

- **Com 2, a estimativa da carga inteira acerta** nesta máquina (base toda em
  memória). Consulta a consulta, o erro continua em torno de meia ordem de
  grandeza — e esse número varia entre rodadas, porque consultas de décimos
  de milissegundo são dominadas por ruído; não é medida confiável.
- **Abaixo de 2, o consultor recomenda um índice que piora o sistema.** Ele
  acrescenta `products(product_id, department_id, product_name)`, e na q15 o
  planejador troca o hash join paralelo (4 workers, leitura sequencial) por
  um laço aninhado com 4.007 buscas no índice de `order_products`: a consulta
  fica ~2,5× mais lenta que sem índice nenhum, e a carga inteira dobra. O
  custo estimado prometia 21% a menos. Só a prova no relógio pega isso.
- `recomendar` e `provar` aceitam `--random-page-cost`; o `provar` marca
  **REGRESSÃO** em consulta que fica mais lenta que sem índice.

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
uv run python -m consultor calibrar              # testa random_page_cost 4, 2, 1,5, 1,1 e 1
uv run python -m consultor site                  # site/data/resultados.json para a página
```

O Kaggle precisa de token em `~/.kaggle/access_token`. A competição original
exige aceitar as regras no site; o espelho acima tem os mesmos arquivos
(contagens conferidas: 3.421.083 pedidos, 32.434.489 + 1.384.617 itens).

## Limites conhecidos

- **Guloso não desfaz escolha.** Se `(product_id)` entra primeiro,
  `(product_id, order_id)` depois ganha pouco e não entra, mesmo que sozinho
  fosse melhor que o primeiro.
- **Custo do planejador como função objetivo.** Herda os erros dele. Calibrar
  o `random_page_cost` corrige a carga inteira, mas valor baixo demais leva a
  recomendação ruim (ver calibração) — a prova no relógio não é opcional.
- **Escrita não entra na conta.** Índice deixa `INSERT`/`UPDATE` mais caros; a
  carga aqui é só leitura.
- **Só B-tree.** `LIKE 'prefixo%'` pediria `text_pattern_ops`; busca textual
  pediria GIN/trigram.
