"""Custo estimado de uma consulta sob uma configuração de índices hipotéticos.

A HypoPG cria o índice só no catálogo da sessão: o planejador o enxerga, o
disco não. Cada avaliação é reset → criar os hipotéticos da configuração →
EXPLAIN → ler o custo total. Só os índices das tabelas que a consulta lê
entram na chave do cache: um índice em products não muda o custo de uma
consulta que só lê orders, e sem isso o cache quase não acertaria.
"""

from .banco import Consulta
from .candidatos import Indice, plano


class Avaliador:
    def __init__(self, conn, tabelas_por_consulta: dict[str, set[str]]):
        self.conn = conn
        self.tabelas = tabelas_por_consulta
        self.cache: dict[tuple[str, frozenset], float] = {}
        self.explains = 0
        self._tamanhos: dict[Indice, int] = {}

    def custo(self, c: Consulta, config: frozenset[Indice]) -> float:
        relevantes = frozenset(i for i in config if i.tabela in self.tabelas[c.nome])
        chave = (c.nome, relevantes)
        if chave not in self.cache:
            self.conn.execute("SELECT hypopg_reset()")
            for i in relevantes:
                self.conn.execute("SELECT * FROM hypopg_create_index(%s)", (i.ddl,))
            self.cache[chave] = plano(self.conn, c.sql)["Total Cost"]
            self.explains += 1
        return self.cache[chave]

    def custo_total(self, consultas: list[Consulta], config: frozenset[Indice]) -> float:
        return sum(c.peso * self.custo(c, config) for c in consultas)

    def tamanho(self, i: Indice) -> int:
        """Bytes que o índice ocuparia, pela estimativa da própria HypoPG."""
        if i not in self._tamanhos:
            self.conn.execute("SELECT hypopg_reset()")
            oid = self.conn.execute("SELECT indexrelid FROM hypopg_create_index(%s)", (i.ddl,)).fetchone()[0]
            self._tamanhos[i] = self.conn.execute("SELECT hypopg_relation_size(%s)", (oid,)).fetchone()[0]
        return self._tamanhos[i]

    def indices_usados(self, c: Consulta, config: frozenset[Indice]) -> set[str]:
        """Que índices hipotéticos o plano escolheu de fato (pelo nome que a
        HypoPG dá: "<oid>btree_tabela_coluna")."""
        self.conn.execute("SELECT hypopg_reset()")
        nomes = {}
        for i in config:
            if i.tabela in self.tabelas[c.nome]:
                oid, nome = self.conn.execute(
                    "SELECT indexrelid, indexname FROM hypopg_create_index(%s)", (i.ddl,)).fetchone()
                nomes[nome] = i
        usados = set()

        def andar(p):
            if p.get("Index Name") in nomes:
                usados.add(str(nomes[p["Index Name"]]))
            for f in p.get("Plans", []):
                andar(f)
        andar(plano(self.conn, c.sql))
        return usados
