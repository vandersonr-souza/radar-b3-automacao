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


def regularidade_bazin(proventos: list[Provento] | None, serie_precos: list[tuple] | None,
                       preco_atual: float, hoje: date, piso: float = 6.0) -> dict | None:
    """Critério de Bazin ("Faça Fortuna com Ações"): os TRÊS últimos dividendos
    anuais, cada um com cash-yield SEMPRE >= 6% -- não a média.

    Cada ano é uma janela de 12 meses pela data-ex (0-12, 12-24, 24-36 meses
    atrás), e o cash-yield de cada janela usa o preço do FIM daquela janela
    (o preço da época), não o de hoje. Ano sem provento = 0 (reprova).

    None quando não dá para afirmar: sem proventos informados, sem série de
    preços, ou a série não alcança 3 anos (ex.: IPO recente).
    -> {"dpa": [ano0, ano1, ano2], "cash_yield": [...], "regular": bool}"""
    if proventos is None or not serie_precos or not preco_atual or preco_atual <= 0:
        return None
    serie = sorted((d, float(p)) for d, p in serie_precos if p and p > 0)
    inicio_necessario = hoje - timedelta(days=365 * 3)
    if not serie or serie[0][0] > inicio_necessario + timedelta(days=7):
        return None                                   # histórico não cobre 3 anos
    dpas, yields = [], []
    for k in range(3):
        fim = hoje - timedelta(days=365 * k)
        ini = fim - timedelta(days=365)
        dpa = round(sum(p.valor_por_acao for p in proventos if ini < p.data_ex <= fim), 6)
        if k == 0:
            preco_fim = preco_atual
        else:
            anteriores = [p for d, p in serie if d <= fim]
            if not anteriores:
                return None
            preco_fim = anteriores[-1]
        dpas.append(dpa)
        yields.append(round(dpa / preco_fim * 100, 2))
    return {"dpa": dpas, "cash_yield": yields, "regular": all(y >= piso for y in yields)}
