"""Cálculos determinísticos a partir de proventos. Nenhuma fonte fornece o
DY pronto para nós: cada uma usa janela e escala próprias, então o número
que vai para a base é calculado aqui, sempre do mesmo jeito."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from .base import Provento


def dy_12m(proventos: list[Provento] | None, preco: float, data_ref: date) -> float | None:
    """DY dos últimos 12 meses, em %, pela data-ex.

    None quando não dá para afirmar nada: fonte sem suporte a proventos,
    lista vazia (ausência de registro não prova que a empresa não pagou)
    ou preço inválido. Regra do projeto: dado ausente nunca vira número."""
    if not proventos or not preco or preco <= 0:
        return None
    inicio = data_ref - timedelta(days=365)
    soma = sum(p.valor_por_acao for p in proventos if inicio < p.data_ex <= data_ref)
    return round(soma / preco * 100, 2)


def dpa_por_ano(proventos: list[Provento] | None) -> dict[int, float]:
    """Soma dos proventos por ano civil da data-ex. Base para verificar a
    regularidade de 3 anos do Bazin com dado real. Ano sem registro fica
    fora do dicionário (não vira 0)."""
    anos: dict[int, float] = defaultdict(float)
    for p in proventos or []:
        anos[p.data_ex.year] += p.valor_por_acao
    return {a: round(v, 6) for a, v in sorted(anos.items())}
