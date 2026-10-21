"""Conexão com o Postgres do docker-compose e leitura da carga de trabalho."""

import os
import re
from dataclasses import dataclass
from pathlib import Path

import psycopg

RAIZ = Path(__file__).resolve().parent.parent
DSN = os.environ.get("CONSULTOR_DSN", "postgresql://consultor:consultor@127.0.0.1:5433/instacart")


def conectar() -> psycopg.Connection:
    # autocommit: EXPLAIN e hypopg_* não precisam de transação, e uma
    # transação aberta seguraria snapshot durante a busca inteira
    return psycopg.connect(DSN, autocommit=True)


@dataclass(frozen=True)
class Consulta:
    nome: str
    peso: float
    sql: str


def carga_de_trabalho(pasta: Path = RAIZ / "carga_trabalho") -> list[Consulta]:
    """Um arquivo por consulta; a linha `-- peso: N` diz quantas vezes por
    hora ela roda. Sem peso declarado, a consulta não entra: um peso
    adivinhado decide sozinho o resultado do consultor."""
    consultas = []
    for arq in sorted(pasta.glob("*.sql")):
        texto = arq.read_text()
        m = re.search(r"^--\s*peso:\s*([\d.]+)", texto, re.M)
        if not m:
            raise ValueError(f"{arq.name}: falta a linha '-- peso: N'")
        sql = "\n".join(l for l in texto.splitlines() if not l.lstrip().startswith("--")).strip().rstrip(";")
        consultas.append(Consulta(arq.stem, float(m.group(1)), sql))
    return consultas
