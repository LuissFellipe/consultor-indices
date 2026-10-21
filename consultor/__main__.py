"""Uso:

    uv run python -m consultor recomendar [--orcamento-mb 1024] [--limiar 0.01]
    uv run python -m consultor provar          # cria os recomendados e mede antes/depois
    uv run python -m consultor limpar          # remove todo índice que não é chave primária
"""

import argparse
import json
import time

from .banco import RAIZ, carga_de_trabalho, conectar
from .candidatos import Indice, gerar
from .custo import Avaliador
from .guloso import escolher
from .medir import medir_carga

RESULTADOS = RAIZ / "resultados"


def indices_secundarios(conn):
    return conn.execute("""
        SELECT i.indexrelid::regclass::text
        FROM pg_index i JOIN pg_class t ON t.oid = i.indrelid
        WHERE t.relnamespace = 'public'::regnamespace AND NOT i.indisprimary
    """).fetchall()


def cmd_limpar(_):
    conn = conectar()
    for (nome,) in indices_secundarios(conn):
        conn.execute(f"DROP INDEX {nome}")
        print(f"removido {nome}")


def cmd_recomendar(args):
    conn = conectar()
    if indices_secundarios(conn):
        # o consultor parte do banco sem índices secundários; com eles, o
        # candidato "novo" pode ser um que já existe e o ganho sai zero
        raise SystemExit("há índices secundários no banco: rode `limpar` antes")
    cs = carga_de_trabalho()
    t0 = time.time()
    todos, _, usos, _ = gerar(conn, cs)
    av = Avaliador(conn, {n: u.tabelas for n, u in usos.items()})
    rodadas, inicial = escolher(av, cs, todos, args.orcamento_mb * 1024**2, args.limiar)
    cfg = frozenset(r.indice for r in rodadas)
    print(f"{len(cs)} consultas, {len(todos)} candidatos, {av.explains} EXPLAINs, {time.time() - t0:.1f} s\n")
    print(f"custo estimado da carga: {inicial:,.0f}")
    for r in rodadas:
        print(f"  + {str(r.indice):44} {r.tamanho / 1024**2:7.1f} MB (estimado)  → {r.custo_depois / inicial:6.1%} do custo")
    print()
    por_consulta = {}
    for c in cs:
        a, d = av.custo(c, frozenset()), av.custo(c, cfg)
        usados = sorted(av.indices_usados(c, cfg))
        por_consulta[c.nome] = {"peso": c.peso, "custo_antes": a, "custo_depois": d, "usa": usados}
        print(f"  {c.nome:34} {a:11,.0f} → {d:11,.0f}  ×{a / d:7.1f}  {', '.join(usados) or '—'}")
    conn.execute("SELECT hypopg_reset()")
    RESULTADOS.mkdir(exist_ok=True)
    (RESULTADOS / "recomendacao.json").write_text(json.dumps({
        "orcamento_mb": args.orcamento_mb, "limiar": args.limiar, "custo_inicial": inicial,
        "indices": [{"tabela": r.indice.tabela, "colunas": r.indice.colunas, "tamanho_estimado": r.tamanho,
                     "ganho": r.ganho, "custo_depois": r.custo_depois} for r in rodadas],
        "consultas": por_consulta,
    }, indent=1, ensure_ascii=False))


def cmd_provar(_):
    conn = conectar()
    rec = json.loads((RESULTADOS / "recomendacao.json").read_text())
    cs = carga_de_trabalho()
    print("medindo sem os índices…")
    antes = medir_carga(conn, cs)
    tamanhos = {}
    for i in rec["indices"]:
        ix = Indice(i["tabela"], tuple(i["colunas"]))
        nome = f"ix_{ix.tabela}_{'_'.join(ix.colunas)}"
        t = time.time()
        conn.execute(f"CREATE INDEX {nome} ON {ix.tabela} ({', '.join(ix.colunas)})")
        real = conn.execute("SELECT pg_relation_size(%s::regclass)", (nome,)).fetchone()[0]
        tamanhos[str(ix)] = {"estimado": i["tamanho_estimado"], "real": real}
        print(f"criado {nome}: {time.time() - t:.1f} s, {real / 1024**2:.1f} MB "
              f"(HypoPG estimou {i['tamanho_estimado'] / 1024**2:.1f} MB)")
    for t in {i["tabela"] for i in rec["indices"]}:
        conn.execute(f"ANALYZE {t}")
    print("medindo com os índices…")
    depois = medir_carga(conn, cs)
    tot_a = sum(c.peso * antes[c.nome] for c in cs)
    tot_d = sum(c.peso * depois[c.nome] for c in cs)
    est = rec["consultas"]
    print(f"\n  {'consulta':34} {'antes':>10} {'depois':>10} {'real':>9} {'estimado':>9}")
    for c in cs:
        e = est[c.nome]
        print(f"  {c.nome:34} {antes[c.nome]:8.2f}ms {depois[c.nome]:8.2f}ms "
              f"×{antes[c.nome] / max(depois[c.nome], 1e-3):8.1f} ×{e['custo_antes'] / e['custo_depois']:8.1f}")
    print(f"\ncarga ponderada por hora: {tot_a / 1000:.1f} s → {tot_d / 1000:.1f} s ({tot_d / tot_a:.1%})")
    custo_final = rec["indices"][-1]["custo_depois"] if rec["indices"] else rec["custo_inicial"]
    print(f"estimativa do planejador: {custo_final / rec['custo_inicial']:.1%} do custo")
    (RESULTADOS / "prova.json").write_text(json.dumps(
        {"antes_ms": antes, "depois_ms": depois, "tamanhos": tamanhos,
         "carga_antes_s": tot_a / 1000, "carga_depois_s": tot_d / 1000}, indent=1))


def main():
    p = argparse.ArgumentParser(prog="consultor")
    sub = p.add_subparsers(required=True)
    r = sub.add_parser("recomendar")
    r.add_argument("--orcamento-mb", type=int, default=1024)
    r.add_argument("--limiar", type=float, default=0.01,
                   help="ganho mínimo de uma rodada, como fração do custo atual")
    r.set_defaults(f=cmd_recomendar)
    sub.add_parser("provar").set_defaults(f=cmd_provar)
    sub.add_parser("limpar").set_defaults(f=cmd_limpar)
    args = p.parse_args()
    args.f(args)


if __name__ == "__main__":
    main()
