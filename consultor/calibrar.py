"""Quanto do erro da estimativa vem do random_page_cost.

Para cada valor testado, três números por consulta:

    custo hipotético   EXPLAIN com o índice da HypoPG (tamanho sem deduplicação)
    custo real         EXPLAIN com o índice criado de verdade
    tempo              EXPLAIN ANALYZE, antes e depois

A diferença entre hipotético e real é o erro da HypoPG; a diferença entre
real e o relógio é o erro do modelo de custo. Misturados, não dá para saber
qual dos dois um ajuste de configuração corrige.

A recomendação também é refeita em cada valor: se o modelo de custo muda,
o guloso pode escolher outros índices.
"""

import math
import statistics

from .banco import Consulta
from .candidatos import Indice, gerar, plano
from .custo import Avaliador
from .guloso import escolher
from .medir import tempo_ms


def ajustar(conn, valor: float):
    conn.execute(f"SET random_page_cost = {valor}")


def erro_log(estimado: float, real: float) -> float:
    """Quantas ordens de grandeza a estimativa erra (0 = acertou, 1 = 10×)."""
    return abs(math.log10(estimado / real))


def calibrar(conn, consultas: list[Consulta], valores: list[float], config: list[Indice],
             orcamento_bytes: int, repeticoes: int = 3) -> dict:
    """`config` é o conjunto cujo ganho real se mede (o recomendado no padrão),
    para que todos os valores sejam comparados contra o mesmo par de índices."""
    resultado = {"valores": valores, "config": [str(i) for i in config], "por_valor": {}}
    # fase 1: sem índices secundários — recomendação, custo sem e hipotético, tempo antes
    for v in valores:
        ajustar(conn, v)
        todos, _, usos, _ = gerar(conn, consultas)
        av = Avaliador(conn, {n: u.tabelas for n, u in usos.items()})
        rodadas, inicial = escolher(av, consultas, todos, orcamento_bytes)
        cfg = frozenset(config)
        resultado["por_valor"][v] = {
            "recomendados": [str(r.indice) for r in rodadas],
            "custo_inicial": inicial,
            "custo_final_recomendado": rodadas[-1].custo_depois if rodadas else inicial,
            "consultas": {c.nome: {"custo_sem": av.custo(c, frozenset()), "custo_hipo": av.custo(c, cfg)}
                          for c in consultas},
        }
        conn.execute("SELECT hypopg_reset()")
        for c in consultas:
            resultado["por_valor"][v]["consultas"][c.nome]["ms_sem"] = tempo_ms(conn, c, repeticoes)
    # fase 2: com os índices reais — custo real e tempo depois
    nomes = []
    for i in config:
        nome = f"cal_{i.tabela}_{'_'.join(i.colunas)}"
        conn.execute(f"CREATE INDEX {nome} ON {i.tabela} ({', '.join(i.colunas)})")
        nomes.append(nome)
    for t in {i.tabela for i in config}:
        conn.execute(f"ANALYZE {t}")
    try:
        for v in valores:
            ajustar(conn, v)
            for c in consultas:
                d = resultado["por_valor"][v]["consultas"][c.nome]
                d["custo_real"] = plano(conn, c.sql)["Total Cost"]
                d["ms_com"] = tempo_ms(conn, c, repeticoes)
        # fase 3: onde o guloso recomendou outro conjunto, ele vale no relógio?
        # Um valor baixo demais faz o planejador confiar em acesso aleatório
        # e recomendar índice que piora a consulta; só medindo se vê.
        base = {str(i) for i in config}
        extras_por_valor = {v: [x for x in resultado["por_valor"][v]["recomendados"] if x not in base]
                            for v in valores}
        for extras in {tuple(e) for e in extras_por_valor.values() if e}:
            criados = []
            for x in extras:
                tabela, cols = x[:-1].split("(")
                nome = f"cal_extra_{len(criados)}"
                conn.execute(f"CREATE INDEX {nome} ON {tabela} ({cols})")
                conn.execute(f"ANALYZE {tabela}")
                criados.append(nome)
            try:
                for v in valores:
                    if tuple(extras_por_valor[v]) != extras:
                        continue
                    ajustar(conn, v)
                    for c in consultas:
                        resultado["por_valor"][v]["consultas"][c.nome]["ms_com_recomendado"] = tempo_ms(conn, c, repeticoes)
            finally:
                for nome in criados:
                    conn.execute(f"DROP INDEX {nome}")
    finally:
        for nome in nomes:
            conn.execute(f"DROP INDEX {nome}")
        conn.execute("RESET random_page_cost")
    # resumo: erro em ordens de grandeza, só nas consultas que ganharam algo
    for v in valores:
        cs = resultado["por_valor"][v]["consultas"]
        com_ganho = [n for n, d in cs.items() if d["ms_sem"] / d["ms_com"] >= 2]
        def mediana(chave):
            return statistics.median(
                erro_log(cs[n]["custo_sem"] / cs[n][chave], cs[n]["ms_sem"] / cs[n]["ms_com"]) for n in com_ganho)
        pesos = {c.nome: c.peso for c in consultas}
        resultado["por_valor"][v]["resumo"] = {
            "consultas_com_ganho": len(com_ganho),
            "erro_mediano_hipo": mediana("custo_hipo"),
            "erro_mediano_real": mediana("custo_real"),
            "carga_estimada_hipo": sum(pesos[n] * d["custo_hipo"] for n, d in cs.items())
                                   / sum(pesos[n] * d["custo_sem"] for n, d in cs.items()),
            "carga_estimada_real": sum(pesos[n] * d["custo_real"] for n, d in cs.items())
                                   / sum(pesos[n] * d["custo_sem"] for n, d in cs.items()),
            "carga_medida": sum(pesos[n] * d["ms_com"] for n, d in cs.items())
                            / sum(pesos[n] * d["ms_sem"] for n, d in cs.items()),
            # o que o próprio conjunto recomendado naquele valor faz no relógio
            "carga_medida_recomendado": sum(pesos[n] * d.get("ms_com_recomendado", d["ms_com"]) for n, d in cs.items())
                                        / sum(pesos[n] * d["ms_sem"] for n, d in cs.items()),
            "regressoes": sorted(n for n, d in cs.items()
                                 if d.get("ms_com_recomendado", d["ms_com"]) > 1.2 * d["ms_sem"]),
        }
    return resultado
