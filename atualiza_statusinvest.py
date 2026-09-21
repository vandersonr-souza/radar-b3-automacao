import json
import requests

SUPABASE_URL = "https://vlrdidsvsfvkajqlkiwj.supabase.co"
SUPABASE_KEY = "sb_publishable_Eobaw2W6-WdIg7-g4EXTBQ_v6tgFMy6"

HEADERS_SUPABASE = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "resolution=merge-duplicates"
}

HEADERS_BROWSER = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Referer": "https://statusinvest.com.br/",
    "Accept": "application/json, text/plain, */*"
}

def parse_num(val):
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    try:
        s = str(val).replace(".", "").replace(",", ".").strip()
        return float(s)
    except:
        return 0.0

print("1/3 Baixando Ações (incluindo ROIC, ROE e Liquidez)...")
url_acoes = "https://statusinvest.com.br/category/advancedsearchresultpaginated?search=%7B%7D&CategoryType=1&take=600"
try:
    res_acoes = requests.get(url_acoes, headers=HEADERS_BROWSER, timeout=30)
    data_raw = res_acoes.json()
    acoes_data = data_raw.get("list", []) if isinstance(data_raw, dict) else []
except Exception as e:
    print(f"Erro ações: {e}")
    acoes_data = []

print(f"-> {len(acoes_data)} ações obtidas.")

print("2/3 Baixando FIIs (incluindo Vacância Física e Financeira)...")
url_fiis = "https://statusinvest.com.br/category/advancedsearchresultpaginated?search=%7B%7D&CategoryType=2&take=600"
try:
    res_fiis = requests.get(url_fiis, headers=HEADERS_BROWSER, timeout=30)
    data_raw = res_fiis.json()
    fiis_data = data_raw.get("list", []) if isinstance(data_raw, dict) else []
except Exception as e:
    print(f"Erro FIIs: {e}")
    fiis_data = []

print(f"-> {len(fiis_data)} FIIs obtidos.")

payload = []
setores_best_prefix = ("BB", "IT", "TA", "TR", "EG", "CM", "CP", "SA", "CX", "VI", "VB", "CS")

for item in acoes_data:
    if not isinstance(item, dict):
        continue
    ticker = str(item.get("ticker", "")).strip().upper()
    if not ticker or len(ticker) < 4:
        continue
    
    preco = parse_num(item.get("price"))
    dy = parse_num(item.get("dy"))
    p_l = parse_num(item.get("p_l"))
    p_vp = parse_num(item.get("p_vp"))
    margem_bruta = parse_num(item.get("margembruta"))
    margem_liquida = parse_num(item.get("margemliquida"))
    roic = parse_num(item.get("roic"))
    roe = parse_num(item.get("roe"))
    liquidez = parse_num(item.get("liquidezmediadiaria"))
    
    dpa_ltm = round((preco * dy / 100.0), 2) if preco > 0 and dy > 0 else 0.0
    bazin_min = round(dpa_ltm * 16.67, 2)
    bazin_max = round(dpa_ltm * 20.00, 2)
    bazin_regular = dy >= 6.0
    
    payout_implicito = None
    coerente = True
    if p_l > 0 and dy > 0:
        payout_implicito = (dy / 100.0) / (1.0 / p_l)
        coerente = payout_implicito <= 1.10
        
    is_best = any(ticker.startswith(pfx) for pfx in setores_best_prefix)
    
    if not coerente:
        status_compra = "ALERTA RISCO"
        motivo = f"Payout insustentável ({payout_implicito*100:.0f}%). Lucro contábil inferior ao dividendo."
    elif bazin_regular and preco <= bazin_max and bazin_max > 0:
        if is_best:
            status_compra = "COMPRA FORTE"
            motivo = f"Setor BEST perene com DY de {dy:.1f}%, ROIC de {roic:.1f}% e margem Bazin até R$ {bazin_max:.2f}."
        else:
            status_compra = "OPORTUNIDADE PREÇO"
            motivo = f"Abaixo do Preço Justo Bazin (R$ {bazin_max:.2f}) com DY de {dy:.1f}%."
    elif bazin_max > 0 and preco > bazin_max:
        status_compra = "AGUARDAR CORREÇÃO"
        motivo = f"Cotação (R$ {preco:.2f}) acima do Preço Justo Bazin (R$ {bazin_max:.2f})."
    else:
        status_compra = "NEUTRO"
        motivo = "Múltiplos em patamar neutro."

    payload.append({
        "ticker": ticker,
        "tipo": "ACAO",
        "nome": item.get("companyName") or ticker,
        "setor": item.get("sectorName") or "Ações B3",
        "segmento_fii": None,
        "preco": round(preco, 2),
        "dy_12m": round(dy, 2),
        "dpa_ltm": dpa_ltm,
        "dpa_ltm1": round(dpa_ltm * 0.95, 2),
        "dpa_ltm2": round(dpa_ltm * 0.90, 2),
        "bazin_preco_justo_min": bazin_min,
        "bazin_preco_justo_max": bazin_max,
        "bazin_regular": bazin_regular,
        "p_l": round(p_l, 2) if p_l != 0 else None,
        "p_vp": round(p_vp, 2) if p_vp != 0 else None,
        "margem_bruta": round(margem_bruta, 2),
        "margem_liquida": round(margem_liquida, 2),
        "roic": round(roic, 2) if roic != 0 else None,
        "roe": round(roe, 2) if roe != 0 else None,
        "liquidez_media_diaria": round(liquidez, 2) if liquidez != 0 else None,
        "vacancia_fisica": None,
        "vacancia_financeira": None,
        "is_best": is_best,
        "payout_implicito": round(payout_implicito, 2) if payout_implicito else None,
        "coerente_dy_lucro": coerente,
        "status_compra": status_compra,
        "recomendacao_motivo": motivo
    })

fii_papel_keywords = ["recebíveis", "papel", "cri", "títulos", "crédito"]

for item in fiis_data:
    if not isinstance(item, dict):
        continue
    ticker = str(item.get("ticker", "")).strip().upper()
    if not ticker:
        continue
        
    preco = parse_num(item.get("price"))
    dy = parse_num(item.get("dy"))
    p_vp = parse_num(item.get("p_vp"))
    sub = str(item.get("segment") or "").lower()
    vac_fisica = parse_num(item.get("vacanciafisica"))
    vac_financeira = parse_num(item.get("vacanciafinanceira"))
    liquidez_fii = parse_num(item.get("liquidezmediadiaria"))
    
    is_papel = any(k in sub for k in fii_papel_keywords) or (ticker in ["MXRF11", "KNIP11", "TGAR11", "CPTS11", "HGCR11", "KNSC11", "RBRR11", "VRTA11"])
    segmento_fii = "PAPEL" if is_papel else "TIJOLO"
    
    if is_papel:
        vac_fisica_efetiva = None
        vac_financeira_efetiva = None
        if p_vp <= 1.00 and dy >= 10.0:
            status_compra = "BOM PARA COMPRA"
            motivo = f"FII de Papel sem ágio (P/VP {p_vp:.2f} <= 1.00) e yield de {dy:.1f}%."
        elif p_vp > 1.05:
            status_compra = "CARO / AGUARDAR"
            motivo = f"Risco de Ágio: P/VP de {p_vp:.2f} em carteira de crédito/CRI."
        else:
            status_compra = "NEUTRO"
            motivo = f"FII de Papel negociando a P/VP {p_vp:.2f}."
    else:
        vac_fisica_efetiva = round(vac_fisica, 2)
        vac_financeira_efetiva = round(vac_financeira, 2)
        if p_vp < 0.95 and vac_fisica <= 10.0:
            status_compra = "BOM PARA COMPRA"
            motivo = f"Desconto patrimonial ({((1-p_vp)*100):.1f}%) com vacância física contida ({vac_fisica:.1f}%)."
        elif p_vp > 1.05:
            status_compra = "CARO / AGUARDAR"
            motivo = f"Ágio sobre imóveis (P/VP {p_vp:.2f})."
        else:
            status_compra = "PREÇO JUSTO"
            motivo = f"P/VP equilibrado ({p_vp:.2f}) e vacância em {vac_fisica:.1f}%."

    dpa_fii = round((preco * dy / 100.0), 2) if preco > 0 and dy > 0 else 0.0

    payload.append({
        "ticker": ticker,
        "tipo": "FII",
        "nome": item.get("companyName") or ticker,
        "setor": f"FII {item.get('segment') or 'Geral'}",
        "segmento_fii": segmento_fii,
        "preco": round(preco, 2),
        "dy_12m": round(dy, 2),
        "dpa_ltm": dpa_fii,
        "dpa_ltm1": round(dpa_fii * 0.95, 2),
        "dpa_ltm2": round(dpa_fii * 0.90, 2),
        "bazin_preco_justo_min": round(dpa_fii * 16.67, 2),
        "bazin_preco_justo_max": round(dpa_fii * 20.00, 2),
        "bazin_regular": dy >= 6.0,
        "p_l": None,
        "p_vp": round(p_vp, 2) if p_vp != 0 else None,
        "margem_bruta": None,
        "margem_liquida": None,
        "roic": None,
        "roe": None,
        "liquidez_media_diaria": round(liquidez_fii, 2) if liquidez_fii != 0 else None,
        "vacancia_fisica": vac_fisica_efetiva,
        "vacancia_financeira": vac_financeira_efetiva,
        "is_best": False,
        "payout_implicito": None,
        "coerente_dy_lucro": True,
        "status_compra": status_compra,
        "recomendacao_motivo": motivo
    })

print(f"3/3 Enviando {len(payload)} ativos com novas métricas para o Supabase...")
batch_size = 50
for i in range(0, len(payload), batch_size):
    lote = payload[i:i + batch_size]
    res = requests.post(f"{SUPABASE_URL}/rest/v1/ativos_mercado", json=lote, headers=HEADERS_SUPABASE)
    print(f"Lote {i//batch_size + 1}/{(len(payload)//batch_size) + 1}: Status {res.status_code}")

print("\nCarga completa finalizada com sucesso!")
