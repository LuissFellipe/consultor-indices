"""Tempo real das consultas, para conferir a estimativa contra o relógio.

EXPLAIN (ANALYZE, TIMING OFF): executa a consulta de verdade e devolve o
"Execution Time" sem o custo de cronometrar cada nó do plano. Uma execução de
aquecimento e depois a mediana de N, com o cache do Postgres já quente — o que
se mede é o plano, não o disco frio da primeira leitura.
"""

import json
import statistics

from .banco import Consulta


def tempo_ms(conn, c: Consulta, repeticoes: int = 3) -> float:
    def uma():
        linha = conn.execute(f"EXPLAIN (ANALYZE, TIMING OFF, FORMAT JSON) {c.sql}").fetchone()[0]
        return (json.loads(linha) if isinstance(linha, str) else linha)[0]["Execution Time"]
    uma()
    return statistics.median(uma() for _ in range(repeticoes))


def medir_carga(conn, consultas: list[Consulta], repeticoes: int = 3) -> dict[str, float]:
    conn.execute("SELECT hypopg_reset()")
    return {c.nome: tempo_ms(conn, c, repeticoes) for c in consultas}
