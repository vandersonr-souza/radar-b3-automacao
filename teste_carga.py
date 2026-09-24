import os, json
os.environ["SUPABASE_SERVICE_KEY"] = "chave-de-teste-fake"
os.environ["FONTE_DADOS"] = "statusinvest"  # este teste cobre o caminho antigo
from unittest import mock

ACOES = [
    {"ticker":"SANB11","sectorName":"Bancos","price":30.0,"dy":9.0,"p_l":9.0,"p_vp":1.1,"liquidezmediadiaria":5e6},
    {"ticker":"CSNA3","sectorName":"Siderurgia e Metalurgia","price":15.0,"dy":8.0,"p_l":6.0,"p_vp":0.9,"liquidezmediadiaria":3e6},
    {"ticker":"BBAS3","sectorName":"Bancos","price":23.20,"dy":0.6,"p_l":10.8,"p_vp":0.73,"liquidezmediadiaria":9e6},
    {"ticker":"SEMP3","sectorName":"Bancos","price":None,"dy":5.0,"p_l":5.0,"p_vp":1.0},
]
FIIS = [
    {"ticker":"HGLG11","segment":"Logística","price":161.0,"dy":9.0,"p_vp":0.94,"vacanciafisica":5.8,"vacanciafinanceira":7.4,"liquidezmediadiaria":2e6},
    {"ticker":"XPML11","segment":"Shoppings","price":100.0,"dy":9.5,"p_vp":0.90,"vacanciafisica":None,"vacanciafinanceira":None,"liquidezmediadiaria":1.5e6},
    {"ticker":"ZERO11","segment":"Logística","price":0,"dy":9.0,"p_vp":0.9},
]

class R:
    def __init__(s, corpo, status=200, texto=None):
        s._c, s.status_code = corpo, status
        s.text = texto if texto is not None else json.dumps(corpo)
    def json(s):
        if isinstance(s._c, str): raise ValueError("não é JSON")
        return s._c

def rodar(get_fn, post_status_hist=201):
    posts = []
    def fp(url, json=None, headers=None, timeout=None):
        posts.append((url, json))
        return R({}, post_status_hist if "historico" in url else 201)
    ns = {"__name__": "__main__"}
    codigo = None
    with mock.patch("requests.get", side_effect=get_fn), mock.patch("requests.post", side_effect=fp):
        try: exec(compile(open("atualiza_statusinvest.py", encoding="utf-8").read(), "x", "exec"), ns)
        except SystemExit as e: codigo = e.code
    return ns, posts, codigo

normal = lambda url, **k: R({"list": ACOES if "CategoryType=1" in url else FIIS})

print("=== 1. carga normal ===")
ns, posts, cod = rodar(normal)
assert cod is None, f"não deveria sair com erro, saiu {cod}"
pl = {p["ticker"]: p for p in ns["payload"]}
assert "SEMP3" not in pl and "ZERO11" not in pl, "ativos sem preço não podem ser gravados"
assert ns["sem_preco"] == ["SEMP3", "ZERO11"]
principais = [p for u, p in posts if u.endswith("/ativos_mercado")]
hist = [p for u, p in posts if "ativos_mercado_historico" in u]
assert sum(map(len, principais)) == 5 and sum(map(len, hist)) == 5
assert all("on_conflict=ticker,data_ref" in u for u, _ in posts if "historico" in u)
h = hist[0][0]
assert set(h) >= {"ticker","data_ref","preco","p_vp","atualizado_em"} and len(h["data_ref"]) == 10
assert {x["atualizado_em"] for l in hist for x in l} == {ns["ATUALIZADO_EM"]}
xp = [x for l in hist for x in l if x["ticker"] == "XPML11"][0]
assert xp["vacancia_fisica"] is None, "histórico também não pode inventar vacância"
print(f"  ✅ 5 gravados, 2 sem preço descartados, histórico 5 linhas, data_ref={h['data_ref']}")

print("=== 2. regressões das correções anteriores ===")
assert pl["CSNA3"]["is_best"] is False
assert pl["HGLG11"]["bazin_preco_justo_max"] is None
assert pl["XPML11"]["vacancia_fisica"] is None
assert pl["BBAS3"]["faixa_payout"] == "incoerente_baixo"
assert all(p["dpa_ltm1"] is None for p in ns["payload"])
print("  ✅ BEST, Bazin fora de FII, vacância nula, payout BBAS3, DPA fabricado: intactos")

print("=== 3. Status Invest devolve HTML (bloqueio) ===")
ns, posts, cod = rodar(lambda url, **k: R("<html>desafio</html>", 200, "<html>desafio</html>"))
assert cod == 1 and posts == [], "tem que abortar SEM gravar nada"
print("  ✅ aborta com código 1, zero gravações")

print("=== 4. só FIIs falham (HTTP 403) ===")
ns, posts, cod = rodar(lambda url, **k: R({"list": ACOES}) if "CategoryType=1" in url else R({}, 403, "Forbidden"))
assert cod == 1 and posts == []
print("  ✅ carga parcial também aborta sem gravar")

print("=== 5. JSON sem o campo 'list' ===")
ns, posts, cod = rodar(lambda url, **k: R({"erro": "mudou"}))
assert cod == 1 and posts == []
print("  ✅ mudança de formato da fonte aborta")

print("=== 6. tabela de histórico não existe (404) ===")
ns, posts, cod = rodar(normal, post_status_hist=404)
assert cod == 1
assert sum(len(p) for u, p in posts if u.endswith("/ativos_mercado")) == 5
print("  ✅ principal gravada, job marcado como falho com mensagem clara")

print("=== 7. lista exatamente no limite (600) gera aviso ===")
import io, contextlib
muitas = [dict(ACOES[0], ticker=f"AAAA{i}") for i in range(600)]
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    rodar(lambda url, **k: R({"list": muitas if "CategoryType=1" in url else FIIS}))
assert "AVISO: ações: 600 linhas" in buf.getvalue()
print("  ✅ aviso de possível corte emitido")
print("\n🎉 todos os cenários passaram")
