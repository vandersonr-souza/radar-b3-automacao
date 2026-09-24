"""Plugue brapi.dev (API com contrato).

Formatos confirmados na documentação oficial (brapi.dev/docs, set/2026):
  Cotação   GET /api/v2/stocks/quote?symbols=A,B
            -> results[].{symbol, data.regularMarketPrice}
  Proventos GET /api/v2/stocks/dividends?symbols=A&startDate=YYYY-MM-DD
            -> results[].data.cashDividends[].{rate, exDate, lastDatePrior,
               paymentDate, label}
A doc diz que PETR4, VALE3, MGLU3 e ITUB4 respondem sem token, mas em
24/set a v2 exigiu token para todos (ver disponivel). Token: variável
de ambiente BRAPI_TOKEN (header Authorization: Bearer).

VERIFICADO em 24/set (rodada real): o plano GRATUITO aceita 1 ativo por
requisição (HTTP 400 com a mensagem "Seu plano permite no máximo 1
ativo(s) por requisição"); o plano Startup aceita 10. Padrão: BRAPI_LOTE=1.
Com plano pago, defina BRAPI_LOTE=10. NÃO VERIFICADO: a cota diária de
requisições do plano gratuito.
'rate' é o valor por ação na escala de preços AJUSTADA (o valor sem ajuste,
rawRate, exige plano Pro) -- consistente com o preço atual para o DY.
"""
from __future__ import annotations

import os
from datetime import date, timedelta

from ._http import data_iso, em_lotes, get_json
from .base import Cotacao, ErroProvedor, Provento, ProvedorMercado, normalizar_ticker

BASE = "https://brapi.dev/api/v2/stocks"


class BrapiProvedor(ProvedorMercado):
    nome = "brapi"
    requer_chave = True

    def __init__(self, token: str | None = None, lote: int | None = None):
        self.token = token if token is not None else os.environ.get("BRAPI_TOKEN", "")
        self.lote = lote or int(os.environ.get("BRAPI_LOTE", "1"))

    def _headers(self):
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def disponivel(self):
        # VERIFICADO em 24/set (Actions): sem token, a v2 responde HTTP 401
        # MISSING_TOKEN até para PETR4/VALE3/ITUB4 -- a documentação diz que
        # esses respondem sem token, mas na prática não. Sem token = desligado.
        if not self.token:
            return False, "variável BRAPI_TOKEN não definida (a API v2 exige token)"
        return True, ""

    def cotacoes(self, tickers):
        saida = {}
        for lote in em_lotes([normalizar_ticker(t) for t in tickers], self.lote):
            try:
                dados = get_json(f"{BASE}/quote", params={"symbols": ",".join(lote)},
                                 headers=self._headers(), rotulo=f"brapi quote {lote[:3]}...")
            except ErroProvedor as e:
                print(f"  [brapi] {e}")
                continue  # lote perdido; os tickers dele seguem para o próximo provedor
            for r in (dados or {}).get("results") or []:
                sym = normalizar_ticker(str(r.get("symbol") or r.get("requestedSymbol") or ""))
                preco = ((r.get("data") or {}).get("regularMarketPrice"))
                try:
                    saida[sym] = Cotacao(sym, float(preco), self.nome,
                                         momento=None)
                except (TypeError, ValueError):
                    continue  # preço ausente/ inválido para este ticker
        return saida

    def proventos(self, ticker, desde: date):
        t = normalizar_ticker(ticker)
        # startDate filtra por data de PAGAMENTO; pedimos com folga e
        # filtramos localmente pela data-ex.
        params = {"symbols": t, "startDate": (desde - timedelta(days=120)).isoformat()}
        try:
            dados = get_json(f"{BASE}/dividends", params=params, headers=self._headers(),
                             rotulo=f"brapi dividends {t}")
        except ErroProvedor as e:
            print(f"  [brapi] {e}")
            return None
        resultados = (dados or {}).get("results") or []
        if not resultados:
            return None
        lista = []
        for d in ((resultados[0].get("data") or {}).get("cashDividends") or []):
            data_ex = data_iso(d.get("exDate")) or data_iso(d.get("lastDatePrior"))
            try:
                valor = float(d.get("rate"))
            except (TypeError, ValueError):
                continue
            if data_ex is None or valor <= 0 or data_ex < desde:
                continue
            lista.append(Provento(t, valor, data_ex, self.nome, tipo=str(d.get("label") or ""),
                                  data_pagamento=data_iso(d.get("paymentDate"))))
        return lista
