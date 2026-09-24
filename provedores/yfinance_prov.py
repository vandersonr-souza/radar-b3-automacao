"""Plugue yfinance (gratuito, NÃO-oficial: lê dados do Yahoo Finance).

Sem chave. Ticker da B3 no Yahoo leva o sufixo ".SA".

UMA requisição por ativo, 37 meses (3 anos + folga, para a regularidade
de Bazin), mesma requisição de antes. (24/set, após a 1ª carga real no Actions ser
limitada pelo Yahoo com YFRateLimitError): Ticker.history(period="13mo",
actions=True) já traz o fechamento E a coluna Dividends (valor por ação na
data-ex). Antes eram duas (history + .dividends), sem pausa -- ~2.500
requisições em 3 minutos. Agora:
  - pausa entre ativos (YF_PAUSA, padrão 0,5 s);
  - ao ser limitado, espera e tenta de novo (YF_ESPERAS, padrão 20,60 s);
  - disjuntor: se YF_DISJUNTOR ativos seguidos (padrão 3) continuarem
    limitados mesmo após as esperas, o plugue para de consultar nesta
    execução -- insistir só prolonga o bloqueio. O que faltar segue para
    o próximo provedor da cascata (ou fica de fora, com a linha antiga).
  - proventos() usa o que cotacoes() já baixou (nenhuma requisição extra).

NÃO VERIFICADO: se o Yahoo registra JCP bruto ou líquido de IR; e o limite
exato de requisições do Yahoo (não é publicado).
"""
from __future__ import annotations

import os
import threading
import time

from .base import Cotacao, Provento, ProvedorMercado, normalizar_ticker


def _e_limite(exc: Exception) -> bool:
    return "ratelimit" in type(exc).__name__.lower() or "too many requests" in str(exc).lower()


class YFinanceProvedor(ProvedorMercado):
    nome = "yfinance"
    requer_chave = False

    def __init__(self, pausa: float | None = None, esperas: list[float] | None = None,
                 disjuntor: int | None = None, dormir=time.sleep):
        try:
            import yfinance  # noqa: F401  (import tardio: dependência opcional)
            self._yf = yfinance
        except ImportError:
            self._yf = None
        self.pausa = pausa if pausa is not None else float(os.environ.get("YF_PAUSA", "0.5"))
        self.esperas = esperas if esperas is not None else [
            float(x) for x in os.environ.get("YF_ESPERAS", "20,60").split(",") if x.strip()]
        self.disjuntor = disjuntor if disjuntor is not None else int(os.environ.get("YF_DISJUNTOR", "3"))
        self._dormir = dormir
        self._cache: dict[str, tuple | None] = {}   # ticker -> (preco, momento, [(data, valor)], [(data, fech)]) | None
        self._limitados_seguidos = 0
        self.bloqueado = False
        self._trava = threading.Lock()

    def disponivel(self):
        if self._yf is None:
            return False, "biblioteca yfinance não instalada (pip install yfinance)"
        return True, ""

    # -- uma requisição por ativo, com esperas e disjuntor -------------------
    def _baixar(self, t: str):
        if t in self._cache:
            return self._cache[t]
        if self.bloqueado:
            return None
        for tentativa in range(len(self.esperas) + 1):
            try:
                hist = self._yf.Ticker(f"{t}.SA").history(period="37mo", auto_adjust=False, actions=True)
                self._limitados_seguidos = 0
                break
            except Exception as e:
                if _e_limite(e) and tentativa < len(self.esperas):
                    espera = self.esperas[tentativa]
                    print(f"  [yfinance] limite do Yahoo em {t}; esperando {espera:.0f}s "
                          f"(tentativa {tentativa + 1}/{len(self.esperas)})")
                    self._dormir(espera)
                    continue
                if _e_limite(e):
                    self._limitados_seguidos += 1
                    if self._limitados_seguidos >= self.disjuntor:
                        self.bloqueado = True
                        print(f"  [yfinance] DISJUNTOR: {self._limitados_seguidos} ativos seguidos "
                              "limitados mesmo após as esperas. Parando de consultar o Yahoo nesta execução.")
                else:
                    print(f"  [yfinance] {t}: {type(e).__name__}: {e}")
                self._cache[t] = None
                return None
        self._dormir(self.pausa)

        if hist is None or getattr(hist, "empty", True) or "Close" not in hist:
            self._cache[t] = None
            return None
        fech = hist["Close"].dropna()
        if fech.empty:
            self._cache[t] = None
            return None
        divs = []
        if "Dividends" in hist:
            for idx, v in hist["Dividends"].items():
                try:
                    v = float(v)
                except (TypeError, ValueError):
                    continue
                if v > 0:
                    divs.append((idx.date() if hasattr(idx, "date") else idx, v))
        serie = [((i.date() if hasattr(i, "date") else i), float(v)) for i, v in fech.items()]
        self._cache[t] = (float(fech.iloc[-1]), fech.index[-1].to_pydatetime(), divs, serie)
        return self._cache[t]

    def cotacoes(self, tickers):
        saida = {}
        for bruto in tickers:
            t = normalizar_ticker(bruto)
            with self._trava:
                dado = self._baixar(t)
            if dado is None:
                continue
            try:
                saida[t] = Cotacao(t, dado[0], self.nome, momento=dado[1])
            except ValueError:
                continue
        return saida

    def proventos(self, ticker, desde):
        t = normalizar_ticker(ticker)
        with self._trava:
            dado = self._baixar(t)
        if dado is None:
            return None               # não sei (não baixou) -- nunca "não pagou"
        return [Provento(t, v, d, self.nome) for d, v in dado[2] if d >= desde]

    def serie_precos(self, ticker):
        t = normalizar_ticker(ticker)
        with self._trava:
            dado = self._baixar(t)
        return None if dado is None else dado[3]
