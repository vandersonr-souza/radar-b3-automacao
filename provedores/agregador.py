"""Cascata de provedores: o primeiro tenta todos os tickers; o que ficar
faltando vai para o segundo; e assim por diante. Cada dado sai carimbado
com a fonte. Provedor que quebra inteiro não derruba a carga."""
from __future__ import annotations

from datetime import date

from .base import Cotacao, ErroProvedor, Provento, ProvedorMercado, normalizar_ticker


def buscar_cotacoes(tickers: list[str], provedores: list[ProvedorMercado]):
    """-> (cotacoes {ticker: Cotacao}, faltando [tickers sem nenhuma fonte],
           resumo {fonte: quantidade})"""
    pendentes = list(dict.fromkeys(normalizar_ticker(t) for t in tickers))
    achadas: dict[str, Cotacao] = {}
    resumo: dict[str, int] = {}
    for prov in provedores:
        if not pendentes:
            break
        try:
            obtidas = prov.cotacoes(pendentes)
        except ErroProvedor as e:
            print(f"  [{prov.nome}] falhou inteiro, seguindo para o próximo: {e}")
            continue
        except Exception as e:  # plugue com bug não pode derrubar a carga
            print(f"  [{prov.nome}] erro inesperado ({type(e).__name__}: {e}), seguindo")
            continue
        novos = {t: c for t, c in obtidas.items() if t in pendentes}
        achadas.update(novos)
        resumo[prov.nome] = len(novos)
        pendentes = [t for t in pendentes if t not in novos]
    return achadas, pendentes, resumo


def buscar_proventos(ticker: str, desde: date, provedores: list[ProvedorMercado]):
    """Primeiro provedor que SABE informar proventos (não devolve None)
    vence. -> (lista ou None, nome da fonte ou None)."""
    for prov in provedores:
        try:
            lista = prov.proventos(ticker, desde)
        except Exception as e:
            print(f"  [{prov.nome}] proventos {ticker}: {type(e).__name__}: {e}")
            continue
        if lista is not None:
            return lista, prov.nome
    return None, None
