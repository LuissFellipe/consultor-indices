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


def ajustar_custo(conn, args):
    if getattr(args, "random_page_cost", None) is not None:
        conn.execute(f"SET random_page_cost = {float(args.random_page_cost)}")


def cmd_recomendar(args):
    conn = conectar()
    ajustar_custo(conn, args)
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
        "candidatos": len(todos), "explains": av.explains,
        "indices": [{"tabela": r.indice.tabela, "colunas": r.indice.colunas, "tamanho_estimado": r.tamanho,
                     "ganho": r.ganho, "custo_depois": r.custo_depois} for r in rodadas],
        "consultas": por_consulta,
    }, indent=1, ensure_ascii=False))


def cmd_provar(args):
    conn = conectar()
    ajustar_custo(conn, args)
    if indices_secundarios(conn):
        # o "antes" tem que ser o banco sem índices, senão a prova compara
        # índice com índice — e o CREATE INDEX falharia pelo nome repetido
        raise SystemExit("há índices secundários no banco: rode `limpar` antes")
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
        # 20% de folga: abaixo disso é ruído de medição em consulta de milissegundos
        alerta = "  ⚠ REGRESSÃO" if depois[c.nome] > 1.2 * antes[c.nome] and depois[c.nome] - antes[c.nome] > 1 else ""
        print(f"  {c.nome:34} {antes[c.nome]:8.2f}ms {depois[c.nome]:8.2f}ms "
              f"×{antes[c.nome] / max(depois[c.nome], 1e-3):8.1f} ×{e['custo_antes'] / e['custo_depois']:8.1f}{alerta}")
    print(f"\ncarga ponderada por hora: {tot_a / 1000:.1f} s → {tot_d / 1000:.1f} s ({tot_d / tot_a:.1%})")
    custo_final = rec["indices"][-1]["custo_depois"] if rec["indices"] else rec["custo_inicial"]
    print(f"estimativa do planejador: {custo_final / rec['custo_inicial']:.1%} do custo")
    (RESULTADOS / "prova.json").write_text(json.dumps(
        {"antes_ms": antes, "depois_ms": depois, "tamanhos": tamanhos,
         "carga_antes_s": tot_a / 1000, "carga_depois_s": tot_d / 1000}, indent=1))


def cmd_calibrar(args):
    from .calibrar import calibrar

    conn = conectar()
    if indices_secundarios(conn):
        raise SystemExit("há índices secundários no banco: rode `limpar` antes")
    rec = json.loads((RESULTADOS / "recomendacao.json").read_text())
    config = [Indice(i["tabela"], tuple(i["colunas"])) for i in rec["indices"]]
    t0 = time.time()
    r = calibrar(conn, carga_de_trabalho(), args.valores, config, rec["orcamento_mb"] * 1024**2)
    print(f"{time.time() - t0:.0f} s\n")
    print("erro = ordens de grandeza entre ganho estimado e medido, mediana das consultas com ganho")
    print("carga = custo ou tempo da carga ponderada com os índices, relativo a sem índices\n")
    for v in args.valores:
        p = r["por_valor"][v]
        s = p["resumo"]
        print(f"random_page_cost = {v}")
        print(f"  recomendados: {', '.join(p['recomendados'])}")
        print(f"  erro: {s['erro_mediano_hipo']:.2f} com índice hipotético, {s['erro_mediano_real']:.2f} com índice real")
        print(f"  carga com os 2 de referência: estimada {s['carga_estimada_real']:.1%}, medida {s['carga_medida']:.1%}")
        print(f"  carga com os recomendados neste valor: medida {s['carga_medida_recomendado']:.1%}"
              + (f"  ⚠ mais lenta que sem índice: {', '.join(s['regressoes'])}" if s["regressoes"] else ""))
    (RESULTADOS / "calibracao.json").write_text(json.dumps(r, indent=1))


def cmd_site(_):
    """Junta recomendação, prova e carga de trabalho num JSON para site/."""
    import re

    rec = json.loads((RESULTADOS / "recomendacao.json").read_text())
    prova = json.loads((RESULTADOS / "prova.json").read_text())
    consultas = []
    for c in carga_de_trabalho():
        texto = (RAIZ / "carga_trabalho" / f"{c.nome}.sql").read_text()
        comentario = [l[2:].strip() for l in texto.splitlines() if l.startswith("--") and "peso:" not in l]
        e = rec["consultas"][c.nome]
        consultas.append({
            "id": c.nome[:3], "nome": c.nome, "descricao": " ".join(comentario), "peso": c.peso, "sql": c.sql,
            "custo_antes": e["custo_antes"], "custo_depois": e["custo_depois"], "usa": e["usa"],
            "ms_antes": prova["antes_ms"][c.nome], "ms_depois": prova["depois_ms"][c.nome],
        })
    rodadas = [{"indice": f"{i['tabela']}({', '.join(i['colunas'])})", "custo": i["custo_depois"],
                "tamanho_estimado": i["tamanho_estimado"],
                "tamanho_real": prova["tamanhos"][f"{i['tabela']}({', '.join(i['colunas'])})"]["real"]}
               for i in rec["indices"]]
    calibracao = []
    arq_cal = RESULTADOS / "calibracao.json"
    if arq_cal.exists():
        cal = json.loads(arq_cal.read_text())
        for v in cal["valores"]:
            pv = cal["por_valor"][str(v)]
            calibracao.append({
                "random_page_cost": v, "recomendados": pv["recomendados"],
                "estimada": pv["custo_final_recomendado"] / pv["custo_inicial"],
                "medida": pv["resumo"]["carga_medida_recomendado"],
                "regressoes": pv["resumo"]["regressoes"],
            })
    saida = RAIZ / "site/data"
    saida.mkdir(parents=True, exist_ok=True)
    (saida / "resultados.json").write_text(json.dumps({
        "custo_inicial": rec["custo_inicial"], "orcamento_mb": rec["orcamento_mb"], "limiar": rec["limiar"],
        "candidatos": rec.get("candidatos"), "explains": rec.get("explains"),
        "rodadas": rodadas, "consultas": consultas, "calibracao": calibracao,
        "carga_antes_s": prova["carga_antes_s"], "carga_depois_s": prova["carga_depois_s"],
    }, ensure_ascii=False, indent=1))
    print(f"site/data/resultados.json: {len(consultas)} consultas, {len(rodadas)} índices")


def main():
    p = argparse.ArgumentParser(prog="consultor")
    sub = p.add_subparsers(required=True)
    r = sub.add_parser("recomendar")
    r.add_argument("--orcamento-mb", type=int, default=1024)
    r.add_argument("--limiar", type=float, default=0.01,
                   help="ganho mínimo de uma rodada, como fração do custo atual")
    r.add_argument("--random-page-cost", type=float,
                   help="sem a opção, vale o do servidor (4); `calibrar` mostra que 2 acerta nesta máquina")
    r.set_defaults(f=cmd_recomendar)
    pv = sub.add_parser("provar")
    pv.add_argument("--random-page-cost", type=float)
    pv.set_defaults(f=cmd_provar)
    sub.add_parser("limpar").set_defaults(f=cmd_limpar)
    sub.add_parser("site").set_defaults(f=cmd_site)
    k = sub.add_parser("calibrar", help="testa valores de random_page_cost")
    k.add_argument("--valores", type=float, nargs="+", default=[4.0, 2.0, 1.5, 1.1, 1.0])
    k.set_defaults(f=cmd_calibrar)
    args = p.parse_args()
    args.f(args)


if __name__ == "__main__":
    main()
