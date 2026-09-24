"""Plugue yfinance (gratuito, NÃO-oficial: lê dados do Yahoo Finance).

Sem chave. Ticker da B3 no Yahoo leva o sufixo ".SA".
Cotação: último 'Close' de Ticker.history(period="5d").
Proventos: Ticker.dividends (série indexada pela data-ex).

NÃO VERIFICADO: se o Yahoo registra JCP pelo valor bruto ou líquido de IR,
e se todos os FIIs têm rendimentos cadastrados. Rodar valida_provedores.py
e comparar com brapi antes de confiar no DY de um ativo específico.
"""
from __future__ import annotations

from .base import Cotacao, Provento, ProvedorMercado, normalizar_ticker


class YFinanceProvedor(ProvedorMercado):
    nome = "yfinance"
    requer_chave = False

    def __init__(self):
        try:
            import yfinance  # noqa: F401  (import tardio: dependência opcional)
            self._yf = yfinance
        except ImportError:
            self._yf = None

    def disponivel(self):
        if self._yf is None:
            return False, "biblioteca yfinance não instalada (pip install yfinance)"
        return True, ""

    def cotacoes(self, tickers):
        saida = {}
        for bruto in tickers:
            t = normalizar_ticker(bruto)
            try:
                hist = self._yf.Ticker(f"{t}.SA").history(period="5d", auto_adjust=False)
                if hist is None or hist.empty or "Close" not in hist:
                    continue
                fech = hist["Close"].dropna()
                if fech.empty:
                    continue
                momento = fech.index[-1].to_pydatetime()
                saida[t] = Cotacao(t, float(fech.iloc[-1]), self.nome, momento=momento)
            except Exception as e:  # a lib levanta tipos variados; um ticker não derruba o lote
                print(f"  [yfinance] {t}: {type(e).__name__}: {e}")
        return saida

    def proventos(self, ticker, desde):
        t = normalizar_ticker(ticker)
        try:
            serie = self._yf.Ticker(f"{t}.SA").dividends
        except Exception as e:
            print(f"  [yfinance] proventos {t}: {type(e).__name__}: {e}")
            return None
        if serie is None:
            return None
        lista = []
        for idx, valor in serie.items():
            data_ex = idx.date() if hasattr(idx, "date") else idx
            try:
                v = float(valor)
            except (TypeError, ValueError):
                continue
            if v > 0 and data_ex >= desde:
                lista.append(Provento(t, v, data_ex, self.nome))
        return lista
