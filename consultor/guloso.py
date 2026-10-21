"""Escolha gulosa de índices sob orçamento de espaço (estilo AutoAdmin).

    escolhidos = ∅
    repita:
        para cada candidato c:
            ganho(c) = Σ peso(q) · [custo(q | escolhidos) − custo(q | escolhidos ∪ {c})]
        melhor = argmax ganho(c) / tamanho(c), entre os que cabem no orçamento
        pare se ganho(melhor) < limiar · custo atual
        escolhidos ∪= {melhor}

O ganho é recalculado a cada rodada porque índices interagem: depois que
(user_id, order_number) entrou, um (user_id) sozinho não ganha mais nada —
servia às mesmas consultas. Somar os ganhos isolados escolheria os dois.

Dividir pelo tamanho é o que faz o orçamento funcionar como mochila: um
índice de 700 MB precisa ganhar proporcionalmente mais que um de 2 MB. O
limiar evita o contrário — o índice minúsculo que ganha quase nada, mas que,
dividido por quase nada, parece ótimo.
"""

from dataclasses import dataclass

from .banco import Consulta
from .candidatos import Indice
from .custo import Avaliador


@dataclass
class Rodada:
    indice: Indice
    ganho: float          # em unidades de custo do planejador × peso
    tamanho: int
    custo_depois: float


def escolher(av: Avaliador, consultas: list[Consulta], candidatos: list[Indice],
             orcamento_bytes: int, limiar: float = 0.01) -> tuple[list[Rodada], float]:
    escolhidos: frozenset[Indice] = frozenset()
    atual = av.custo_total(consultas, escolhidos)
    inicial = atual
    usado = 0
    rodadas = []
    restantes = list(candidatos)
    while restantes:
        melhor, melhor_razao, melhor_ganho, melhor_custo = None, 0.0, 0.0, atual
        for c in restantes:
            t = av.tamanho(c)
            if usado + t > orcamento_bytes:
                continue
            custo = av.custo_total(consultas, escolhidos | {c})
            ganho = atual - custo
            if ganho <= 0:
                continue
            razao = ganho / max(t, 8192)
            if razao > melhor_razao:
                melhor, melhor_razao, melhor_ganho, melhor_custo = c, razao, ganho, custo
        if melhor is None or melhor_ganho < limiar * atual:
            break
        escolhidos |= {melhor}
        usado += av.tamanho(melhor)
        atual = melhor_custo
        rodadas.append(Rodada(melhor, melhor_ganho, av.tamanho(melhor), atual))
        restantes.remove(melhor)
    return rodadas, inicial
