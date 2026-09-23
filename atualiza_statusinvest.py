import json
import os
import sys
from datetime import datetime, timezone
import requests

SUPABASE_URL = "https://vlrdidsvsfvkajqlkiwj.supabase.co"

# A chave saiu do código em 22/set. Mesmo sendo "publishable" (pensada pra
# ficar no cliente), ela estava sendo usada pra ESCREVER (INSERT/UPDATE) --
# e com RLS permitindo anon nessas operações, qualquer um que visse este
# repositório público podia sobrescrever a tabela. Depois de corrigir as
# políticas de RLS (só service_role escreve), o certo é este workflow
# também usar a chave service_role, guardada em Settings > Secrets and
# variables > Actions do repositório -- nunca commitada.
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")
if not SUPABASE_KEY:
    print("ERRO: variável de ambiente SUPABASE_SERVICE_KEY não definida. "
          "Configure em Settings > Secrets and variables > Actions.")
    sys.exit(1)

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
    """Converte para float. Ausência de dado vira 0.0 -- só use isto onde
    0 e 'sem dado' realmente significam a mesma coisa para a regra (ex.:
    liquidez, onde ausência e liquidez zero levam à mesma conclusão)."""
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    try:
        s = str(val).replace(".", "").replace(",", ".").strip()
        return float(s)
    except (ValueError, TypeError):
        return 0.0


def parse_num_or_none(val):
    """Mesma conversão, mas preserva a ausência como None.

    Adicionada em 22/set: a versão que sempre devolve 0.0 fazia um FII sem
    dado de vacância parecer ter vacância ZERO -- ou seja, parecer perfeito.
    Use esta função em qualquer campo onde 0 e 'a fonte não trouxe o dado'
    têm significados diferentes: vacância, margens, ROE, ROIC.
    """
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    try:
        s = str(val).replace(".", "").replace(",", ".").strip()
        if s == "":
            return None
        return float(s)
    except (ValueError, TypeError):
        return None

TAKE_STATUSINVEST = 600  # tamanho de página pedido nas URLs (take=600)


def baixar_lista_statusinvest(url, rotulo):
    """Baixa uma lista do Status Invest. Em qualquer falha devolve [] e
    explica o motivo no log; quem decide abortar é a trava de carga vazia
    logo depois dos dois downloads."""
    try:
        res = requests.get(url, headers=HEADERS_BROWSER, timeout=30)
    except requests.RequestException as e:
        print(f"Erro de rede ao baixar {rotulo}: {e}")
        return []
    if not (200 <= res.status_code < 300):
        print(f"Erro ao baixar {rotulo}: HTTP {res.status_code}. Início: {res.text[:200]!r}")
        return []
    try:
        data_raw = res.json()
    except ValueError:
        # Caso típico de bloqueio: status 200 com HTML no corpo.
        print(f"Erro ao baixar {rotulo}: resposta não é JSON (provável bloqueio). "
              f"Início: {res.text[:200]!r}")
        return []
    lista = data_raw.get("list") if isinstance(data_raw, dict) else None
    if not isinstance(lista, list):
        chaves = list(data_raw)[:10] if isinstance(data_raw, dict) else type(data_raw).__name__
        print(f"Erro ao baixar {rotulo}: JSON sem o campo 'list'. Recebido: {chaves}")
        return []
    if len(lista) >= TAKE_STATUSINVEST:
        # Não sabemos se existem mais ativos do que a página pede. Lista
        # exatamente cheia = provável corte silencioso.
        print(f"AVISO: {rotulo}: {len(lista)} linhas, igual ao limite da página "
              f"(take={TAKE_STATUSINVEST}). Pode haver ativos cortados.")
    return lista


print("1/3 Baixando Ações (incluindo ROIC, ROE e Liquidez)...")
url_acoes = "https://statusinvest.com.br/category/advancedsearchresultpaginated?search=%7B%7D&CategoryType=1&take=600"
acoes_data = baixar_lista_statusinvest(url_acoes, "ações")
print(f"-> {len(acoes_data)} ações obtidas.")

print("2/3 Baixando FIIs (incluindo Vacância Física e Financeira)...")
url_fiis = "https://statusinvest.com.br/category/advancedsearchresultpaginated?search=%7B%7D&CategoryType=2&take=600"
fiis_data = baixar_lista_statusinvest(url_fiis, "FIIs")
print(f"-> {len(fiis_data)} FIIs obtidos.")

# Trava de carga vazia (23/set). Antes, se o Status Invest bloqueasse a
# requisição (ex.: página anti-robô em HTML no lugar do JSON), as duas
# listas voltavam vazias, o payload ficava vazio e o script terminava com
# "Carga completa: 0/0 lote(s)" -- job VERDE com a base parada. Lista
# vazia nunca é resultado legítimo para a B3 inteira.
if not acoes_data or not fiis_data:
    faltando = [n for n, l in (("ações", acoes_data), ("FIIs", fiis_data)) if not l]
    print(f"ERRO: nenhuma linha recebida para {' e '.join(faltando)}. "
          "Carga abortada sem gravar nada -- a base mantém a carga anterior "
          "(e o carimbo atualizado_em antigo deixa isso visível no app).")
    sys.exit(1)

payload = []
sem_preco = []  # tickers descartados por não terem cotação

# Um só carimbo para toda a carga do dia -- não um por ativo, senão dois
# ativos processados em milissegundos diferentes pareceriam "de dias
# diferentes" numa comparação. ISO 8601 com fuso, direto em UTC (o app
# converte para exibição; salvar em UTC evita ambiguidade de horário de
# verão).
ATUALIZADO_EM = datetime.now(timezone.utc).isoformat()

# Classificação BEST por SETOR, não por prefixo de ticker.
#
# A versão anterior usava setores_best_prefix = ("BB","IT","TA",...) e
# `ticker.startswith(pfx)`. Testado em 22/set contra tickers reais:
# CSNA3 (siderurgia/commodity), VBBR3 (distribuição de combustível) e
# TASA4 (armas) todos batiam como is_best=True -- exatamente o tipo de
# cíclica que o método Barsi manda EXCLUIR de BEST. Prefixo de 2 letras
# é ainda mais frágil que o "electric" in industry que já corrigimos
# duas vezes no agente principal (Greenblatt e BEST).
#
# ⚠️ NÃO TESTADO contra a resposta real do Status Invest: os nomes de
# setor abaixo (`sectorName`) são a nomenclatura mais comum do site, mas
# precisam ser conferidos no primeiro payload real antes de confiar --
# mesma disciplina dos valida_*.py do projeto principal: nunca integrar
# uma correspondência de texto sem ver o dado de verdade primeiro.
_SETORES_BEST = (
    "bancos", "banco",
    "seguradoras", "seguros", "previdência e seguros",
    "energia elétrica",
    "água e saneamento", "saneamento",
    "telecomunicações", "telecomunicacoes", "telecom",
)


def e_setor_best(nome_setor):
    """True só se o SETOR (não o ticker) contiver um dos rótulos BEST."""
    texto = (nome_setor or "").strip().lower()
    return any(rotulo in texto for rotulo in _SETORES_BEST)

for item in acoes_data:
    if not isinstance(item, dict):
        continue
    ticker = str(item.get("ticker", "")).strip().upper()
    if not ticker or len(ticker) < 4:
        continue
    
    preco = parse_num(item.get("price"))
    if preco <= 0:
        # Sem cotação, não grava: "preco = 0" viraria R$ 0,00 no app, como
        # se fosse dado. A linha antiga (com carimbo antigo) fica na base.
        sem_preco.append(ticker)
        continue
    dy = parse_num(item.get("dy"))
    p_l = parse_num(item.get("p_l"))
    p_vp = parse_num(item.get("p_vp"))
    # margem_bruta/margem_liquida: lidas direto no payload com
    # parse_num_or_none (não aqui) -- 0 e "sem dado" são coisas diferentes
    # para margem, e a versão antiga misturava os dois.
    roic = parse_num(item.get("roic"))
    roe = parse_num(item.get("roe"))
    liquidez = parse_num(item.get("liquidezmediadiaria"))
    
    # DPA aproximado -- é a ÚNICA fonte de proventos que este script tem
    # (não há histórico real coletado aqui, só o DY corrente do Status Invest).
    dpa_ltm = round((preco * dy / 100.0), 2) if preco > 0 and dy > 0 else 0.0

    # bazin_min/bazin_max continuam calculados e enviados -- servem como
    # contexto de "a que preço a cota renderia 5-6% no yield de hoje" --
    # mas NUNCA mais decidem status_compra. Motivo (confirmado por álgebra
    # em 22/set): bazin_max = dpa_ltm*20 = (preco*dy/100)*20 = preco*dy*0.2,
    # então "preco <= bazin_max" se simplifica para "dy >= 5.0" -- o preço
    # se cancela da conta. Comparar preço a um teto DERIVADO DO PRÓPRIO
    # PREÇO é a mesma tautologia que a auditoria do agente principal matou
    # em setembro (Preço Teto = preço × DY / 6%).
    bazin_min = round(dpa_ltm * 16.67, 2)
    bazin_max = round(dpa_ltm * 20.00, 2)

    # dy_atende_criterio_bazin_6pct testa SÓ o yield atual contra 6% --
    # mesmo campo e mesmo nome do agente principal (regras_deterministicas.py).
    # NÃO é "aprovado por Bazin": falta a regularidade de 3 anos, que este
    # script não tem como verificar sem histórico real de proventos.
    dy_atende_criterio_bazin_6pct = dy >= 6.0
    bazin_elegibilidade = "NAO_CONFIRMADA_FALTA_REGULARIDADE_HISTORICA"
    # Mantido só por compatibilidade com quem já lia este campo; é um alias
    # do critério acima, não uma regra nova.
    bazin_regular = dy_atende_criterio_bazin_6pct

    payout_implicito = None
    coerente = True
    faixa_payout = None
    if p_l > 0 and dy > 0:
        payout_implicito = (dy / 100.0) / (1.0 / p_l)
        # Checagem BILATERAL (mesma correção do agente principal, 20/set):
        # payout > 110% denuncia provento maior que o lucro; payout < 10%
        # denuncia DY pequeno demais pro lucro implícito no P/L -- sintoma
        # de campo quebrado na fonte (foi assim que achamos o DY errado do
        # BBAS3 no yfinance). A versão anterior deste script só pegava o
        # lado de cima.
        if payout_implicito > 1.10:
            coerente = False
            faixa_payout = "incoerente_alto"
        elif payout_implicito < 0.10:
            coerente = False
            faixa_payout = "incoerente_baixo"
        else:
            coerente = True
            faixa_payout = "coerente"

    is_best = e_setor_best(item.get("sectorName"))

    # status_compra agora depende do YIELD ATUAL (dy_atende_criterio_bazin_6pct),
    # nunca da comparação tautológica preco<=bazin_max.
    if not coerente:
        status_compra = "ALERTA RISCO"
        if faixa_payout == "incoerente_alto":
            motivo = f"Payout implícito de {payout_implicito*100:.0f}% do lucro -- provento maior que o lucro do período, ou dado de período distinto."
        else:
            motivo = f"DY informado ({dy:.2f}%) é pequeno demais frente ao lucro implícito no P/L (payout {payout_implicito*100:.1f}%) -- possível campo de dividendo quebrado na fonte, não necessariamente yield baixo real."
    elif dy_atende_criterio_bazin_6pct:
        if is_best:
            status_compra = "COMPRA FORTE"
            motivo = f"Setor BEST perene com DY de {dy:.1f}% (atinge o piso de 6% no yield atual) e ROIC de {roic:.1f}%. Regularidade histórica de 3 anos não verificada por esta fonte."
        else:
            status_compra = "OPORTUNIDADE PREÇO"
            motivo = f"DY de {dy:.1f}% atinge o piso de 6% no yield atual. Regularidade histórica de 3 anos não verificada por esta fonte."
    else:
        status_compra = "NEUTRO"
        motivo = f"DY de {dy:.1f}% não atinge o piso de 6% no yield atual."

    payload.append({
        "ticker": ticker,
        "tipo": "ACAO",
        "nome": item.get("companyName") or ticker,
        "setor": item.get("sectorName") or "Ações B3",
        "segmento_fii": None,
        "preco": round(preco, 2),
        "dy_12m": round(dy, 2),
        "dpa_ltm": dpa_ltm,
        # dpa_ltm1/dpa_ltm2 REMOVIDOS em 22/set: eram dpa_ltm*0.95 e
        # dpa_ltm*0.90 -- constantes arbitrárias, não os proventos reais
        # de 12-24 e 24-36 meses atrás. Se um consumidor (ex.: o app
        # Android) usar esses 3 campos para checar "regularidade de 3
        # anos", as 3 janelas viravam versões escaladas do MESMO ponto de
        # dado -- a "regularidade" nunca testava história nenhuma. Melhor
        # não mandar o campo do que mandar um campo que parece verificado
        # e não é. Use bazin_elegibilidade para saber que isso não foi
        # confirmado.
        "dpa_ltm1": None,
        "dpa_ltm2": None,
        "bazin_preco_justo_min": bazin_min,
        "bazin_preco_justo_max": bazin_max,
        # bazin_regular/dy_atende_criterio_bazin_6pct: SÓ o yield atual,
        # nunca "aprovado por Bazin" -- ver bazin_elegibilidade.
        "bazin_regular": bazin_regular,
        "dy_atende_criterio_bazin_6pct": dy_atende_criterio_bazin_6pct,
        "bazin_elegibilidade": bazin_elegibilidade,
        "p_l": round(p_l, 2) if p_l != 0 else None,
        "p_vp": round(p_vp, 2) if p_vp != 0 else None,
        "margem_bruta": parse_num_or_none(item.get("margembruta")),
        "margem_liquida": parse_num_or_none(item.get("margemliquida")),
        "roic": round(roic, 2) if roic != 0 else None,
        "roe": round(roe, 2) if roe != 0 else None,
        "liquidez_media_diaria": round(liquidez, 2) if liquidez != 0 else None,
        "vacancia_fisica": None,
        "vacancia_financeira": None,
        "is_best": is_best,
        "payout_implicito": round(payout_implicito, 2) if payout_implicito is not None else None,
        "faixa_payout": faixa_payout,
        "coerente_dy_lucro": coerente,
        "status_compra": status_compra,
        "recomendacao_motivo": motivo,
        "atualizado_em": ATUALIZADO_EM
    })

fii_papel_keywords = ["recebíveis", "papel", "cri", "títulos", "crédito"]

for item in fiis_data:
    if not isinstance(item, dict):
        continue
    ticker = str(item.get("ticker", "")).strip().upper()
    if not ticker:
        continue
        
    preco = parse_num(item.get("price"))
    if preco <= 0:
        # Sem cotação, não grava: "preco = 0" viraria R$ 0,00 no app, como
        # se fosse dado. A linha antiga (com carimbo antigo) fica na base.
        sem_preco.append(ticker)
        continue
    dy = parse_num(item.get("dy"))
    p_vp = parse_num(item.get("p_vp"))
    sub = str(item.get("segment") or "").lower()
    # parse_num_or_none: um FII SEM dado de vacância não pode parecer um
    # FII com vacância 0% (perfeito). A versão anterior usava parse_num,
    # que confundia os dois casos.
    vac_fisica = parse_num_or_none(item.get("vacanciafisica"))
    vac_financeira = parse_num_or_none(item.get("vacanciafinanceira"))
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
        vac_fisica_efetiva = round(vac_fisica, 2) if vac_fisica is not None else None
        vac_financeira_efetiva = round(vac_financeira, 2) if vac_financeira is not None else None
        # Com parse_num_or_none, vac_fisica pode ser None -- precisa de um
        # caminho próprio, não pode cair nas comparações numéricas de baixo
        # (None <= 10.0 derruba o script com TypeError).
        if vac_fisica is None:
            status_compra = "NEUTRO"
            motivo = f"P/VP de {p_vp:.2f}, mas a fonte não trouxe vacância física para este fundo -- não dá pra confirmar se o desconto/ágio reflete a qualidade dos imóveis."
        elif p_vp < 0.95 and vac_fisica <= 10.0:
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
        # dpa_ltm1/dpa_ltm2 removidos -- mesmo motivo das ações: eram
        # dpa_fii*0.95/0.90, não histórico real (ver comentário acima).
        "dpa_ltm1": None,
        "dpa_ltm2": None,
        # bazin_preco_justo_* e bazin_regular REMOVIDOS para FIIs em
        # 22/set: o método de Décio Bazin ("Faça Fortuna com Ações") é
        # para AÇÕES -- o próprio livro nunca fala de fundo imobiliário.
        # O agente principal já proíbe isso explicitamente no prompt do
        # LLM ("Bazin nunca aplicado a FII") depois de pegar exatamente
        # esse erro de categoria com o KNCR11 numa rodada anterior. Um
        # FII de papel tem DY acompanhando o indexador do CRI (CDI/IPCA)
        # -- yield alto pode ser só repasse de juros, não sinal de
        # qualidade nenhuma relacionada a Bazin.
        "bazin_preco_justo_min": None,
        "bazin_preco_justo_max": None,
        "bazin_regular": None,
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
        "faixa_payout": None,
        "coerente_dy_lucro": True,
        "status_compra": status_compra,
        "recomendacao_motivo": motivo,
        "atualizado_em": ATUALIZADO_EM
    })

if sem_preco:
    print(f"{len(sem_preco)} ativo(s) sem cotação, não gravados: {', '.join(sem_preco[:15])}"
          f"{' ...' if len(sem_preco) > 15 else ''}")

print(f"3/3 Enviando {len(payload)} ativos com novas métricas para o Supabase...")
batch_size = 50
total_lotes = (len(payload) // batch_size) + (1 if len(payload) % batch_size else 0)
lotes_com_falha = 0
for i in range(0, len(payload), batch_size):
    lote = payload[i:i + batch_size]
    numero_lote = i // batch_size + 1
    try:
        res = requests.post(f"{SUPABASE_URL}/rest/v1/ativos_mercado", json=lote,
                             headers=HEADERS_SUPABASE, timeout=30)
    except requests.RequestException as e:
        print(f"Lote {numero_lote}/{total_lotes}: FALHA DE REDE ({e})")
        lotes_com_falha += 1
        continue

    # 2xx é sucesso; qualquer outra coisa é falha real -- a versão anterior
    # só imprimia o código sem checar, e terminava dizendo "sucesso" mesmo
    # que todo lote tivesse voltado 401/403 (ex.: chave sem permissão de
    # escrita depois de uma correção de RLS). Mesma lição do erro 502 do
    # Telegram no agente principal: nunca declarar sucesso sem confirmar.
    if 200 <= res.status_code < 300:
        print(f"Lote {numero_lote}/{total_lotes}: OK (status {res.status_code})")
    else:
        lotes_com_falha += 1
        corpo = res.text[:300]
        print(f"Lote {numero_lote}/{total_lotes}: FALHA -- status {res.status_code}. Corpo: {corpo}")

if lotes_com_falha:
    print(f"\nCarga concluída com {lotes_com_falha}/{total_lotes} lote(s) em falha. "
          f"NÃO declarar sucesso -- confira a chave/política do Supabase.")
    sys.exit(1)  # marca o job do GitHub Actions como falho, não silencioso
else:
    print(f"\nCarga completa: {total_lotes}/{total_lotes} lote(s) confirmados no Supabase.")

# ---------------------------------------------------------------------------
# Histórico diário (23/set). A tabela ativos_mercado é uma FOTO: cada carga
# sobrescreve a anterior. Esta tabela acumula uma linha por ativo por dia,
# enxuta, para que no futuro dê para ver tendência (P/VP, DY, preço) e,
# com 1-2 anos acumulados, derivar DPA de anos anteriores de dado real.
# Chave (ticker, data_ref): rodar duas vezes no mesmo dia atualiza a linha
# do dia em vez de duplicar. Só roda se a carga principal deu certo.
# ---------------------------------------------------------------------------
from zoneinfo import ZoneInfo

DATA_REF = datetime.now(ZoneInfo("America/Sao_Paulo")).date().isoformat()
CAMPOS_HISTORICO = ("ticker", "tipo", "preco", "dy_12m", "dpa_ltm", "p_l", "p_vp",
                    "margem_liquida", "roe", "vacancia_fisica", "liquidez_media_diaria",
                    "faixa_payout", "status_compra")
historico = [{**{c: linha.get(c) for c in CAMPOS_HISTORICO},
              "data_ref": DATA_REF, "atualizado_em": ATUALIZADO_EM} for linha in payload]

print(f"\nGravando histórico do dia {DATA_REF} ({len(historico)} linhas)...")
falhas_hist = 0
lotes_hist = (len(historico) + batch_size - 1) // batch_size
for i in range(0, len(historico), batch_size):
    lote = historico[i:i + batch_size]
    try:
        res = requests.post(f"{SUPABASE_URL}/rest/v1/ativos_mercado_historico?on_conflict=ticker,data_ref",
                            json=lote, headers=HEADERS_SUPABASE, timeout=30)
        ok = 200 <= res.status_code < 300
        if not ok:
            print(f"Histórico lote {i // batch_size + 1}/{lotes_hist}: FALHA -- status "
                  f"{res.status_code}. Corpo: {res.text[:300]}")
    except requests.RequestException as e:
        ok = False
        print(f"Histórico lote {i // batch_size + 1}/{lotes_hist}: FALHA DE REDE ({e})")
    falhas_hist += 0 if ok else 1

if falhas_hist:
    print(f"\nA carga PRINCIPAL foi gravada, mas o HISTÓRICO falhou em "
          f"{falhas_hist}/{lotes_hist} lote(s). Se o erro diz que a tabela não existe, "
          "rode o SQL de criação de ativos_mercado_historico no Supabase.")
    sys.exit(1)
print(f"Histórico completo: {lotes_hist}/{lotes_hist} lote(s) confirmados.")
