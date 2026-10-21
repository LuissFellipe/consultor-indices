# Postgres 17 com HypoPG: índice hipotético, que o EXPLAIN enxerga mas que não
# ocupa disco nem trava tabela. É o que deixa o consultor testar centenas de
# candidatos sem criar nenhum.
FROM postgres:17-bookworm
RUN apt-get update \
 && apt-get install -y --no-install-recommends postgresql-17-hypopg \
 && rm -rf /var/lib/apt/lists/*
COPY init.sql /docker-entrypoint-initdb.d/01-init.sql
