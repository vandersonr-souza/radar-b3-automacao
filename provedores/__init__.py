"""Camada de provedores de mercado do Radar do Mercado.

Cada fonte (yfinance, brapi, HG Brasil, ...) é um "plugue" que implementa
a mesma interface (base.ProvedorMercado). O coletor nunca fala com uma
fonte diretamente: pede ao agregador, que percorre os provedores na ordem
configurada e carimba cada dado com a fonte de onde veio.

Como plugar uma API nova: ver README_PROVEDORES.md.
"""
from .base import Cotacao, Provento, ProvedorMercado, ErroProvedor
from .registro import REGISTRO, carregar_provedores
from .agregador import buscar_cotacoes, buscar_proventos
from .calculos import dy_12m, dpa_por_ano
