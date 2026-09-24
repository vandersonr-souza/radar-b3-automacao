"""Teste ponta a ponta do caminho novo (FONTE_DADOS=cvm_provedores).
Sem rede: base do Supabase, FCA da CVM e provedores são simulados.
Rodar: python teste_coletor.py"""
import io, json, os, zipfile, contextlib
from datetime import date
from unittest import mock

os.environ["SUPABASE_SERVICE_KEY"] = "chave-fake"
os.environ.pop("FONTE_DADOS", None)          # padrão = cvm_provedores

from provedores import base

HOJE = date(2026, 9, 24)

def linha_base(t, tipo, preco, **kw):
    d = {"ticker": t, "tipo": tipo, "preco": preco, "nome": f"Empresa {t}", "setor": None,
         "p_l": None, "p_vp": None, "margem_bruta": None, "margem_liquida": None, "roe": None,
         "roic": None, "liquidez_media_diaria": 1e6, "vacancia_fisica": None,
         "vacancia_financeira": None, "lpa": None, "vpa": None}
    d.update(kw); return d

BASE = [
    linha_base("PETR4", "ACAO", 40.0, p_l=5.0, p_vp=1.0, setor="Petróleo", margem_bruta=47.6, roe=20.0, roic=15.0),
    linha_base("TAEE11", "ACAO", 35.0, p_l=10.0, p_vp=2.0, setor="Energia Elétrica"),
    linha_base("OLDX3", "ACAO", 5.0, p_l=3.0, p_vp=0.5, setor="Varejo"),
    linha_base("HGLG11", "FII", 150.0, p_vp=0.9, setor="FII Logística", vacancia_fisica=5.8, vacancia_financeira=7.4),
    linha_base("XPML11", "FII", 100.0, p_vp=0.95, setor="FII Shoppings"),
    linha_base("SEMP11", "FII", 10.0, p_vp=1.0, setor="FII Híbrido"),
]

def zip_fca(linhas):
    cab = "CNPJ_Companhia;Data_Referencia;Versao;ID_Documento;Nome_Empresarial;Valor_Mobiliario;Sigla_Classe_Acao_Preferencial;Classe_Acao_Preferencial;Codigo_Negociacao;Composicao_BDR_Unit;Mercado;Sigla_Entidade_Administradora;Entidade_Administradora;Data_Inicio_Negociacao;Data_Fim_Negociacao;Segmento;Data_Inicio_Listagem;Data_Fim_Listagem"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("fca_cia_aberta_valor_mobiliario_2026.csv", "\n".join([cab] + linhas).encode("latin-1"))
    return buf.getvalue()

def fca_linha(cnpj, nome, ticker, mercado="Bolsa", fim=""):
    return f"{cnpj};2026-01-01;1;1;{nome};Ações Preferenciais;;;{ticker};;{mercado};B3;B3;2020-01-01;{fim};Novo Mercado;2020-01-01;"

FCA_2026 = zip_fca([fca_linha("33.000.167/0001-01", "PETROBRAS", "PETR4"),
                    fca_linha("11.111.111/0001-11", "NOVA SA", "NOVA3"),
                    fca_linha("22.222.222/0001-22", "OLD SA", "OLDX3", fim="2026-06-30"),
                    fca_linha("33.000.167/0001-01", "PETROBRAS", "", mercado="Balcão Organizado")])

class R:
    def __init__(s, corpo=None, status=200, content=b""):
        s._c, s.status_code, s.content = corpo, status, content
        s.text = json.dumps(corpo) if corpo is not None else ""
    def json(s): return s._c
    def raise_for_status(s):
        if s.status_code >= 400: raise Exception(f"HTTP {s.status_code}")

class Fake(base.ProvedorMercado):
    nome = "fake"
    def __init__(s, precos, proventos): s.precos, s.pv = precos, proventos
    def cotacoes(s, tickers): return {t: base.Cotacao(t, s.precos[t], "fake") for t in tickers if t in s.precos}
    def proventos(s, t, desde): return s.pv.get(t)

PRECOS = {"PETR4": 48.0, "TAEE11": 42.0, "OLDX3": 5.0, "HGLG11": 148.5, "XPML11": 101.0, "NOVA3": 12.0, "SEMP11": 9.0}
PROVENTOS = {
    "PETR4": [base.Provento("PETR4", 1.0, date(2026, 5, 1), "fake"), base.Provento("PETR4", 2.64, date(2026, 8, 20), "fake")],
    "TAEE11": [base.Provento("TAEE11", 3.0, date(2026, 6, 1), "fake")],
    "HGLG11": [base.Provento("HGLG11", 1.1, date(2026, m, 15), "fake") for m in range(1, 10)] +
              [base.Provento("HGLG11", 1.1, date(2025, m, 15), "fake") for m in (10, 11, 12)],
    "XPML11": [base.Provento("XPML11", 0.9, date(2026, 9, 1), "fake")],
    "NOVA3": [],        # fonte sabe informar e não há registro -> DY desconhecido, não 0 real
    # SEMP11: None -> fonte não informa
}

def rodar(base_rows=BASE, precos=PRECOS, fca=FCA_2026, fca_falha=False):
    posts = []
    def fget(url, headers=None, timeout=None, params=None):
        if "supabase.co/rest/v1/ativos_mercado" in url:
            return R(base_rows if "offset=0" in url else [])
        if "fca_cia_aberta_2026" in url:
            if fca_falha: raise ConnectionError("CVM fora do ar")
            return R(status=200, content=fca)
        if "fca_cia_aberta_2025" in url:
            return R(status=404)
        raise AssertionError(f"GET inesperado: {url}")
    def fpost(url, json=None, headers=None, timeout=None):
        posts.append((url, json)); return R({}, 201)
    ns, cod, out = {"__name__": "__main__"}, None, io.StringIO()
    with mock.patch("requests.get", side_effect=fget), mock.patch("requests.post", side_effect=fpost), \
         mock.patch("fontes_dados.carregar_provedores", return_value=[Fake(precos, PROVENTOS)]), \
         mock.patch("fontes_dados.hoje_brasilia", return_value=HOJE), contextlib.redirect_stdout(out):
        try: exec(compile(open("atualiza_statusinvest.py", encoding="utf-8").read(), "x", "exec"), ns)
        except SystemExit as e: cod = e.code
    return ns, posts, cod, out.getvalue()

def ok(m): print("  ✅", m)

print("=== 1. carga normal ===")
ns, posts, cod, log = rodar()
assert cod is None, log[-800:]
pl = {p["ticker"]: p for u, p_ in posts if u.endswith("/ativos_mercado") for p in p_}
assert set(pl) == {"PETR4", "TAEE11", "NOVA3", "HGLG11", "XPML11", "SEMP11"}, set(pl)
ok("OLDX3 (encerrada no FCA) fora; NOVA3 (nova no FCA) dentro; linhas de balcão ignoradas")

p = pl["PETR4"]
assert p["preco"] == 48.0 and p["lpa"] == 8.0 and p["p_l"] == 6.0      # 48 / (40/5)
assert p["vpa"] == 40.0 and p["p_vp"] == 1.2                              # 48 / (40/1)
assert p["dy_12m"] == 7.58                                                # (1,00+2,64)/48
assert p["margem_bruta"] == 47.6 and p["roe"] == 20.0 and p["setor"] == "Petróleo"
ok("PETR4: P/L e P/VP com preço novo e LPA/VPA da última foto (identidade exata); DY dos proventos; margem/ROE mantidos")

t = pl["TAEE11"]
assert t["dy_12m"] == 7.14 and t["is_best"] is True and t["status_compra"] == "COMPRA FORTE"
ok("TAEE11: regras antigas intactas (setor BEST + DY >= 6% -> COMPRA FORTE)")

n = pl["NOVA3"]
assert n["setor"] == "Ações B3" and n["is_best"] is False and n["nome"] == "NOVA SA"
assert n["p_l"] is None and n["lpa"] is None and n["dy_12m"] == 0.0
ok("NOVA3: sem setor conhecido -> não é BEST; sem LPA -> P/L nulo (nunca inventado)")

h = pl["HGLG11"]
assert h["segmento_fii"] == "TIJOLO" and h["setor"] == "FII Logística"
assert h["dy_12m"] == 8.89                                                # 12 x 1,10 / 148,5
assert h["vpa"] == round(150 / 0.9, 6) and h["p_vp"] == round(148.5 / (150 / 0.9), 2)
assert h["vacancia_fisica"] == 5.8 and h["status_compra"] == "BOM PARA COMPRA"
ok("HGLG11: P/VP pelo VPA guardado, vacância mantida, regra de FII tijolo intacta")
assert pl["XPML11"]["vacancia_fisica"] is None and pl["XPML11"]["status_compra"] == "NEUTRO"
ok("XPML11: vacância ausente continua nula -> NEUTRO")
assert "3 sem proventos informados" in log or "sem proventos informados" in log
hist = [x for u, p_ in posts if "historico" in u for x in p_]
assert len(hist) == 6
ok("histórico diário gravado para os 6 ativos")

print("=== 2. segundo dia: LPA guardado vence a identidade ===")
base2 = [dict(r) for r in BASE]
base2[0].update(preco=48.0, p_l=6.01, lpa=8.0)    # p_l arredondado não pode mais mexer no LPA
ns, posts, cod, log = rodar(base_rows=base2)
p = {x["ticker"]: x for u, p_ in posts if u.endswith("/ativos_mercado") for x in p_}["PETR4"]
assert p["lpa"] == 8.0 and p["p_l"] == 6.0
ok("LPA estável entre dias (sem deriva de arredondamento)")

print("=== 3. fontes bloqueadas (cobertura < 50%) ===")
ns, posts, cod, log = rodar(precos={"PETR4": 48.0})
assert cod == 1 and posts == [] and "provável bloqueio" in log
ok("aborta sem gravar nada")

print("=== 4. sql/002 não rodado (sem colunas lpa/vpa) ===")
sem_cols = [{k: v for k, v in r.items() if k not in ("lpa", "vpa")} for r in BASE]
ns, posts, cod, log = rodar(base_rows=sem_cols)
assert cod == 1 and posts == [] and "002_lpa_vpa.sql" in log
ok("aborta com a instrução de rodar o SQL")

print("=== 5. CVM fora do ar ===")
ns, posts, cod, log = rodar(fca_falha=True)
assert cod is None and "FCA da CVM indisponível" in log
tick = {x["ticker"] for u, p_ in posts if u.endswith("/ativos_mercado") for x in p_}
assert "NOVA3" not in tick and "OLDX3" in tick
ok("segue só com a lista da base (FCA é enriquecimento, não ponto único de falha)")
print("\n🎉 todos os cenários passaram")
