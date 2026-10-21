"""Que índices valem a pena testar para cada consulta.

As colunas saem do plano do próprio Postgres (EXPLAIN VERBOSE), não de um
parser de SQL: o planejador já resolveu alias, subconsulta e qual condição
pertence a qual tabela. Cada coluna recebe um papel, e o papel decide onde
ela pode entrar num índice composto:

    igualdade   col = constante        → primeira posição
    intervalo   col < / > / BETWEEN    → depois das igualdades
    junção      col da condição de join → primeira (laço aninhado) ou depois
    ordem       ORDER BY / GROUP BY    → depois das igualdades

É a regra de ouro do B-tree: igualdade na frente, o resto depois. Um índice
(user_id, order_number) atende "WHERE user_id = X ORDER BY order_number"; o
contrário, não.
"""

import json
import re
from dataclasses import dataclass, field
from itertools import permutations

from .banco import Consulta

RE_COL = re.compile(r"\b([a-z_][a-z0-9_]*)\.([a-z_][a-z0-9_]*)\b")
RE_COMPARACAO = re.compile(
    r"\b([a-z_][a-z0-9_]*)\.([a-z_][a-z0-9_]*)\)?(?:::\w+)?\s*(=|<>|<=|>=|<|>|~~)\s*([^()\s]+)"
)


@dataclass(frozen=True)
class Indice:
    tabela: str
    colunas: tuple[str, ...]

    @property
    def ddl(self) -> str:
        return f"CREATE INDEX ON {self.tabela} ({', '.join(self.colunas)})"

    def __str__(self):
        return f"{self.tabela}({', '.join(self.colunas)})"


@dataclass
class Uso:
    """Colunas que uma consulta usa, por tabela e por papel."""
    tabelas: set[str] = field(default_factory=set)
    igualdade: dict[str, set[str]] = field(default_factory=dict)
    intervalo: dict[str, set[str]] = field(default_factory=dict)
    juncao: dict[str, set[str]] = field(default_factory=dict)
    ordem: dict[str, set[str]] = field(default_factory=dict)

    def anotar(self, papel: str, tabela: str, coluna: str):
        getattr(self, papel).setdefault(tabela, set()).add(coluna)


def plano(conn, sql: str, verbose: bool = False) -> dict:
    opcoes = "VERBOSE, FORMAT JSON" if verbose else "FORMAT JSON"
    linha = conn.execute(f"EXPLAIN ({opcoes}) {sql}").fetchone()[0]
    return (json.loads(linha) if isinstance(linha, str) else linha)[0]["Plan"]


def nos(p: dict):
    yield p
    for filho in p.get("Plans", []):
        yield from nos(filho)


def uso_da_consulta(conn, c: Consulta) -> Uso:
    raiz = plano(conn, c.sql, verbose=True)
    alias = {}
    for n in nos(raiz):
        if "Relation Name" in n:
            alias[n.get("Alias", n["Relation Name"])] = n["Relation Name"]
    uso = Uso(tabelas=set(alias.values()))

    def tabela_de(a):
        return alias.get(a)

    for n in nos(raiz):
        for chave in ("Filter", "Index Cond", "Recheck Cond"):
            expr = n.get(chave)
            if not expr:
                continue
            for a, col, op, lado in RE_COMPARACAO.findall(expr):
                t = tabela_de(a)
                if not t:
                    continue
                # "o.user_id = op.user_id" dentro de filtro é junção, não igualdade
                if RE_COL.fullmatch(lado.strip("()")):
                    uso.anotar("juncao", t, col)
                elif op == "=":
                    uso.anotar("igualdade", t, col)
                elif op in ("<", ">", "<=", ">="):
                    uso.anotar("intervalo", t, col)
                elif op == "~~":
                    uso.anotar("intervalo", t, col)
        for chave in ("Hash Cond", "Merge Cond", "Join Filter"):
            for a, col in RE_COL.findall(n.get(chave, "")):
                if (t := tabela_de(a)):
                    uso.anotar("juncao", t, col)
        for chave in ("Sort Key", "Group Key"):
            for expr in n.get(chave, []):
                for a, col in RE_COL.findall(expr):
                    if (t := tabela_de(a)):
                        uso.anotar("ordem", t, col)
    return uso


def indices_existentes(conn) -> list[Indice]:
    linhas = conn.execute("""
        SELECT t.relname, array_agg(a.attname ORDER BY k.ord)
        FROM pg_index i
        JOIN pg_class t ON t.oid = i.indrelid
        JOIN LATERAL unnest(i.indkey) WITH ORDINALITY k(attnum, ord) ON true
        JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = k.attnum
        WHERE t.relnamespace = 'public'::regnamespace
        GROUP BY i.indexrelid, t.relname
    """).fetchall()
    return [Indice(t, tuple(cols)) for t, cols in linhas]


def redundante(c: Indice, existentes: list[Indice]) -> bool:
    """Um índice que é prefixo de outro já existente não acrescenta nada:
    (order_id) não ajuda onde já há (order_id, add_to_cart_order)."""
    return any(e.tabela == c.tabela and e.colunas[: len(c.colunas)] == c.colunas for e in existentes)


def candidatos_da_consulta(uso: Uso, largura_max: int = 3) -> set[Indice]:
    saida = set()
    for t in uso.tabelas:
        ig = uso.igualdade.get(t, set())
        iv = uso.intervalo.get(t, set())
        jn = uso.juncao.get(t, set())
        od = uso.ordem.get(t, set())
        primeiras = ig | iv | jn
        for col in primeiras:
            saida.add(Indice(t, (col,)))
        # composto: igualdade (ou junção) na frente, depois qualquer outro papel
        cabecas = ig | jn
        caudas = ig | iv | jn | od
        for a in cabecas:
            for b in caudas - {a}:
                saida.add(Indice(t, (a, b)))
                if largura_max >= 3:
                    for c in caudas - {a, b}:
                        # terceira coluna só para cobrir a consulta (index-only
                        # scan) quando as duas primeiras são de filtro/junção
                        saida.add(Indice(t, (a, b, c)))
    return saida


def gerar(conn, consultas: list[Consulta], largura_max: int = 3):
    existentes = indices_existentes(conn)
    usos = {c.nome: uso_da_consulta(conn, c) for c in consultas}
    todos = set()
    por_consulta = {}
    for c in consultas:
        cs = {i for i in candidatos_da_consulta(usos[c.nome], largura_max) if not redundante(i, existentes)}
        por_consulta[c.nome] = cs
        todos |= cs
    return sorted(todos, key=str), por_consulta, usos, existentes
