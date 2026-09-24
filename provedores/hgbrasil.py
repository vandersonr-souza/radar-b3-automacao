"""Plugue HG Brasil Finance (API com contrato; plano gratuito com cota diária).

Formato confirmado na documentação oficial (console.hgbrasil.com, set/2026):
  GET https://api.hgbrasil.com/finance/stock_price?key=K&symbol=a,b
  -> {"valid_key": bool, "results": {"PETR4": {"price", "updated_at", ...}
                                      ou {"error": true, "message": ...}}}
Chave: variável de ambiente HGBRASIL_KEY.

Proventos: a HG tem o endpoint stock_dividends, mas NÃO validei o formato
dos campos dele -- por isso este plugue devolve None (= "não informa"),
em vez de arriscar um parser errado. NÃO VERIFICADO também: quantos
símbolos por requisição (HGBRASIL_LOTE, padrão 5).
"""
from __future__ import annotations

import os

from ._http import em_lotes, get_json
from .base import Cotacao, ErroProvedor, ProvedorMercado, normalizar_ticker

URL = "https://api.hgbrasil.com/finance/stock_price"


class HGBrasilProvedor(ProvedorMercado):
    nome = "hgbrasil"
    requer_chave = True

    def __init__(self, chave: str | None = None, lote: int | None = None):
        self.chave = chave if chave is not None else os.environ.get("HGBRASIL_KEY", "")
        self.lote = lote or int(os.environ.get("HGBRASIL_LOTE", "5"))

    def disponivel(self):
        if not self.chave:
            return False, "variável HGBRASIL_KEY não definida"
        return True, ""

    def cotacoes(self, tickers):
        saida = {}
        for lote in em_lotes([normalizar_ticker(t) for t in tickers], self.lote):
            try:
                dados = get_json(URL, params={"key": self.chave, "symbol": ",".join(lote)},
                                 rotulo=f"hgbrasil {lote[:3]}...")
            except ErroProvedor as e:
                print(f"  [hgbrasil] {e}")
                continue
            if isinstance(dados, dict) and dados.get("valid_key") is False:
                raise ErroProvedor("hgbrasil: chave recusada (valid_key=false)")
            for sym, r in ((dados or {}).get("results") or {}).items():
                if not isinstance(r, dict) or r.get("error"):
                    continue
                try:
                    t = normalizar_ticker(sym)
                    saida[t] = Cotacao(t, float(r.get("price")), self.nome)
                except (TypeError, ValueError):
                    continue
        return saida
