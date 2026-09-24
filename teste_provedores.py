"""Testes da camada de provedores. Sem rede: respostas simuladas no formato
documentado de cada fonte. Rodar: python teste_provedores.py"""
import sys, types
from datetime import date, datetime, timezone
from unittest import mock

import pandas as pd

import provedores as P
from provedores import base, calculos
from provedores.brapi import BrapiProvedor
from provedores.hgbrasil import HGBrasilProvedor
from provedores.base import ErroProvedor

class R:
    def __init__(s, corpo, status=200): s._c, s.status_code, s.text = corpo, status, str(corpo)
    def json(s): return s._c

def ok(msg): print("  ✅", msg)

# Checagem de versão (25/set): o repositório já ficou com teste novo e
# plugue antigo, e o erro aparecia só como "AssertionError" sem pista.
import inspect, provedores.yfinance_prov as _yf, provedores.base as _b, provedores.calculos as _c
_faltando = [f"{arq} (procure por '{marca}')" for arq, mod, marca in (
    ("provedores/yfinance_prov.py", _yf, '"37mo"'),
    ("provedores/base.py", _b, "def serie_precos"),
    ("provedores/calculos.py", _c, "def regularidade_bazin"),
) if marca.strip('"') not in inspect.getsource(mod)]
if _faltando:
    raise SystemExit("ARQUIVO(S) DESATUALIZADO(S) NO REPOSITÓRIO: " + "; ".join(_faltando) +
                     ". Substitua pelo arquivo novo DENTRO da pasta provedores/ (não na raiz).")
print("  ✅ versões dos arquivos de provedores conferidas")

print("=== modelo ===")
for ruim in (0, -1, float("nan"), float("inf"), None):
    try: base.Cotacao("X", ruim, "t"); raise AssertionError(f"aceitou {ruim}")
    except (ValueError, TypeError): pass
ok("Cotacao rejeita preço 0, negativo, NaN, infinito e None")

print("=== brapi: cotação (formato v2 documentado) ===")
chamadas = []
def get_brapi(url, params=None, headers=None, timeout=None):
    chamadas.append((url, params))
    syms = params["symbols"].split(",")
    if "VALE3" in syms:                        # simula um lote negado
        return R({"error": True}, 401)
    return R({"results": [{"requestedSymbol": s, "symbol": s, "changed": False,
                           "data": {"regularMarketPrice": 10.0 + i, "currency": "BRL"}}
                          for i, s in enumerate(syms) if s != "SEMPR3"]})
with mock.patch("requests.get", side_effect=get_brapi):
    cot = BrapiProvedor(token="t", lote=2).cotacoes(["petr4", "ITUB4", "VALE3", "MGLU3", "SEMPR3.SA"])
assert set(cot) == {"PETR4", "ITUB4"}, cot                      # lote com VALE3 negado; SEMPR3 sem dado
assert cot["PETR4"].preco == 10.0 and cot["PETR4"].fonte == "brapi"
assert len(chamadas) == 3                                         # 5 tickers / lote 2
ok("lotes de 2, lote negado (401) não derruba os outros, ticker ausente fica de fora, sufixo .SA removido")

print("=== brapi: proventos (formato v2 documentado) ===")
resp_div = {"results": [{"symbol": "ITSA4", "data": {"cashDividends": [
    {"rate": 0.5, "exDate": "2026-08-31T03:00:00.000Z", "paymentDate": "2026-10-01T03:00:00.000Z", "label": "JCP"},
    {"rate": 0.3, "exDate": None, "lastDatePrior": "2026-03-10T03:00:00.000Z", "label": "DIVIDENDO"},
    {"rate": 0.2, "exDate": "2024-01-10T03:00:00.000Z", "label": "DIVIDENDO"},   # antes de 'desde'
    {"rate": "abc", "exDate": "2026-05-01T03:00:00.000Z"},                        # valor inválido
], "stockDividends": []}}]}
with mock.patch("requests.get", return_value=R(resp_div)):
    pv = BrapiProvedor(token="t").proventos("ITSA4", date(2025, 9, 1))
assert [(p.valor_por_acao, p.data_ex, p.tipo) for p in pv] == [
    (0.5, date(2026, 8, 31), "JCP"), (0.3, date(2026, 3, 10), "DIVIDENDO")], pv
assert pv[0].data_pagamento == date(2026, 10, 1)
ok("usa exDate, cai para lastDatePrior, descarta anterior a 'desde' e valor inválido")
with mock.patch("requests.get", return_value=R({}, 403)):
    assert BrapiProvedor(token="").proventos("WEGE3", date(2025, 1, 1)) is None
ok("sem acesso -> None ('não sei'), nunca lista vazia ('não pagou')")

print("=== HG Brasil (formato documentado) ===")
resp_hg = {"by": "symbol", "valid_key": True, "results": {
    "HGLG11": {"kind": "fii", "symbol": "HGLG11", "price": 158.9, "updated_at": "2026-09-23 17:00:00"},
    "EMBR3": {"error": True, "message": "Erro 852 - Símbolo não encontrado"}}}
with mock.patch("requests.get", return_value=R(resp_hg)):
    cot = HGBrasilProvedor(chave="k").cotacoes(["HGLG11", "EMBR3"])
assert set(cot) == {"HGLG11"} and cot["HGLG11"].preco == 158.9
ok("ticker com 'error' fica de fora, o resto passa")
with mock.patch("requests.get", return_value=R({"valid_key": False, "results": {}})):
    try: HGBrasilProvedor(chave="k").cotacoes(["X"]); raise AssertionError
    except ErroProvedor: pass
ok("valid_key=false vira erro do provedor inteiro")
assert HGBrasilProvedor(chave="").disponivel()[0] is False
assert HGBrasilProvedor(chave="k").proventos("X", date(2025, 1, 1)) is None
ok("sem chave = indisponível; proventos = None (formato não validado, não arrisca)")

print("=== yfinance (biblioteca simulada) ===")
idx = pd.to_datetime(["2025-06-02", "2026-02-10", "2026-09-22", "2026-09-23"]).tz_localize("America/Sao_Paulo")
chamadas_yf = []
class LimiteYahoo(Exception): pass
LimiteYahoo.__name__ = "YFRateLimitError"
limites = {}                                   # ticker -> quantas vezes ainda devolve limite
class FakeTicker:
    def __init__(s, sym): s.sym = sym
    def history(s, period, auto_adjust, actions):
        chamadas_yf.append(s.sym)
        assert period == "37mo" and actions is True
        if limites.get(s.sym, 0) > 0:
            limites[s.sym] -= 1; raise LimiteYahoo("Too Many Requests. Rate limited.")
        if s.sym == "ERRO3.SA": raise RuntimeError("falha simulada")
        if s.sym == "VAZIO3.SA": return pd.DataFrame()
        return pd.DataFrame({"Close": [30.0, 31.0, 32.0, 32.5], "Dividends": [0.4, 0.6, 0.0, 0.0]}, index=idx)
fake_yf = types.SimpleNamespace(Ticker=FakeTicker)
esperas_feitas = []
with mock.patch.dict(sys.modules, {"yfinance": fake_yf}):
    import importlib, provedores.yfinance_prov as ymod
    importlib.reload(ymod)
    novo = lambda: ymod.YFinanceProvedor(pausa=0, esperas=[20, 60], disjuntor=2, dormir=esperas_feitas.append)
    yp = novo()
    assert yp.disponivel()[0]
    cot = yp.cotacoes(["PETR4", "ERRO3", "VAZIO3"])
    pv = yp.proventos("PETR4", date(2025, 9, 1))
    assert chamadas_yf.count("PETR4.SA") == 1, chamadas_yf
    ok("UMA requisição por ativo: proventos reaproveitam o que a cotação baixou")
    assert set(cot) == {"PETR4"} and cot["PETR4"].preco == 32.5 and cot["PETR4"].momento.date() == date(2026, 9, 23)
    assert [(p.valor_por_acao, p.data_ex) for p in pv] == [(0.6, date(2026, 2, 10))]
    assert yp.proventos("ERRO3", date(2025, 1, 1)) is None
    ok("último fechamento; dividendos da mesma resposta; falha = None ('não sei'), nunca lista vazia")

    limites.update({"ITUB4.SA": 1})            # limitado 1 vez, depois responde
    esperas_feitas.clear(); yp = novo()
    assert "ITUB4" in yp.cotacoes(["ITUB4"]) and esperas_feitas[:1] == [20]
    ok("limite do Yahoo: espera e tenta de novo, sem perder o ativo")

    limites.update({"AAAA3.SA": 9, "BBBB3.SA": 9, "CCCC3.SA": 9})
    chamadas_yf.clear(); esperas_feitas.clear(); yp = novo()
    cot = yp.cotacoes(["AAAA3", "BBBB3", "CCCC3", "PETR4"])
    assert yp.bloqueado and cot == {} and "CCCC3.SA" not in chamadas_yf and "PETR4.SA" not in chamadas_yf
    ok("disjuntor: 2 ativos seguidos limitados após as esperas -> para de consultar o Yahoo")

with mock.patch.dict(sys.modules, {"yfinance": None}):
    importlib.reload(ymod)
    assert ymod.YFinanceProvedor().disponivel() == (False, "biblioteca yfinance não instalada (pip install yfinance)")
ok("biblioteca ausente = indisponível com motivo, sem quebrar")

print("=== cascata ===")
class Fixo(base.ProvedorMercado):
    def __init__(s, nome, precos, explode=None): s.nome, s.precos, s.explode = nome, precos, explode
    def cotacoes(s, tickers):
        if s.explode: raise s.explode
        return {t: base.Cotacao(t, s.precos[t], s.nome) for t in tickers if t in s.precos}
a = Fixo("A", {"PETR4": 30.0, "VALE3": 60.0})
quebrado = Fixo("Q", {}, explode=RuntimeError("bug no plugue"))
b = Fixo("B", {"VALE3": 99.0, "HGLG11": 158.0})
cot, faltando, resumo = P.buscar_cotacoes(["PETR4", "VALE3", "HGLG11", "XXXX3", "petr4"], [a, quebrado, b])
assert cot["VALE3"].preco == 60.0 and cot["VALE3"].fonte == "A"      # o primeiro vence
assert cot["HGLG11"].fonte == "B" and faltando == ["XXXX3"]
assert resumo == {"A": 2, "B": 1}
ok("primeiro provedor vence, plugue com bug é pulado, resto cai no próximo, duplicata removida, faltantes listados")

print("=== plugar uma API nova (sem tocar no coletor) ===")
class MinhaAPI(base.ProvedorMercado):
    nome = "minhaapi"
    def cotacoes(s, tickers): return {t: base.Cotacao(t, 1.23, s.nome) for t in tickers}
with mock.patch.dict(P.registro.REGISTRO, {"minhaapi": MinhaAPI}), \
     mock.patch.dict("os.environ", {"BRAPI_TOKEN": "", "HGBRASIL_KEY": ""}):
    provs = P.carregar_provedores("minhaapi,hgbrasil", verbose=False)
    assert [p.nome for p in provs] == ["minhaapi"]                    # hgbrasil sem chave, ignorado
    cot, _, _ = P.buscar_cotacoes(["TAEE11"], provs)
    assert cot["TAEE11"].fonte == "minhaapi"
ok("classe nova + 1 linha no REGISTRO + nome em PROVEDORES_ORDEM = funcionando")
try: P.carregar_provedores("brapi,investing", verbose=False); raise AssertionError
except ValueError as e: assert "investing" in str(e)
ok("nome desconhecido na configuração = erro explícito")

print("=== cálculos ===")
pvs = [base.Provento("X", 1.0, date(2025, 10, 1), "t"), base.Provento("X", 0.5, date(2026, 3, 1), "t"),
       base.Provento("X", 2.0, date(2024, 12, 20), "t")]
assert calculos.dy_12m(pvs, 20.0, date(2026, 9, 23)) == 7.5          # (1,0+0,5)/20
assert calculos.dy_12m([], 20.0, date(2026, 9, 23)) is None
assert calculos.dy_12m(None, 20.0, date(2026, 9, 23)) is None
assert calculos.dpa_por_ano(pvs) == {2024: 2.0, 2025: 1.0, 2026: 0.5}
ok("DY 12m pela data-ex; sem proventos = None (nunca 0); DPA por ano civil sem inventar anos")
print("\n🎉 todos os testes passaram")
