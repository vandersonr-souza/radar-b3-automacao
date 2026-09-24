"""fontes_dados.py -- substitui o Status Invest como origem dos dados.

Devolve as listas `acoes_data` e `fiis_data` NO MESMO FORMATO de item que o
Status Invest entregava (chaves "ticker", "price", "dy", "p_l", ...), para
que as regras de atualiza_statusinvest.py rodem sem nenhuma alteração.

De onde vem cada campo (24/set/2026):
  lista de ações  -> última foto da base  ∪  ações ativas no FCA da CVM
                     (menos as que o FCA marca como encerradas)
  lista de FIIs   -> última foto da base (FII ainda não tem fonte oficial
                     de lista integrada -- próxima etapa: informe mensal CVM)
  preço           -> cascata de provedores (provedores/), fresco
  DY 12m          -> calculado por nós a partir dos proventos (calculos.py)
  P/L, P/VP       -> preço de hoje / LPA e VPA guardados na base
                     (1ª carga: LPA = preço/P-L da última foto -- identidade
                     exata, não estimativa)
  margens, ROE, ROIC, liquidez, vacância, segmento, setor, nome
                  -> mantidos da última foto (dados trimestrais). Serão
                     trocados pelos da CVM (DFP/ITR) na próxima etapa.
"""
from __future__ import annotations

import io
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import requests

from provedores import buscar_cotacoes, buscar_proventos, carregar_provedores, dy_12m

FCA_URL = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/FCA/DADOS/fca_cia_aberta_{ano}.zip"
COBERTURA_MINIMA = 0.5   # menos da metade dos ativos com preço = fonte provavelmente bloqueada


class FalhaFonte(Exception):
    """Falha que deve abortar a carga (sem gravar nada)."""


def hoje_brasilia() -> date:
    return datetime.now(ZoneInfo("America/Sao_Paulo")).date()


# ---------------------------------------------------------------------------
# 1. Última foto da base
# ---------------------------------------------------------------------------
def ler_snapshot(supabase_url: str, headers: dict, pagina: int = 1000) -> dict[str, dict]:
    """Lê ativos_mercado inteira, paginando (a API do Supabase devolve no
    máximo um número limitado de linhas por requisição)."""
    linhas, offset = [], 0
    while True:
        url = f"{supabase_url}/rest/v1/ativos_mercado?select=*&order=ticker.asc&limit={pagina}&offset={offset}"
        try:
            res = requests.get(url, headers=headers, timeout=60)
        except requests.RequestException as e:
            raise FalhaFonte(f"não consegui ler a base atual do Supabase: {e}") from e
        if not (200 <= res.status_code < 300):
            raise FalhaFonte(f"leitura da base atual falhou: HTTP {res.status_code} {res.text[:200]}")
        lote = res.json()
        linhas.extend(lote)
        if len(lote) < pagina:
            break
        offset += pagina
    return {str(l.get("ticker", "")).upper(): l for l in linhas if l.get("ticker")}


def exigir_colunas_lpa_vpa(snapshot: dict[str, dict]):
    """As colunas lpa/vpa são criadas pelo sql/002. Sem elas, o P/L e o P/VP
    'andariam' sozinhos com o arredondamento diário -- aborta com instrução."""
    amostra = next(iter(snapshot.values()), {})
    if amostra and ("lpa" not in amostra or "vpa" not in amostra):
        raise FalhaFonte("colunas 'lpa' e 'vpa' não existem em ativos_mercado. "
                         "Rode sql/002_lpa_vpa.sql no Supabase antes desta carga.")


# ---------------------------------------------------------------------------
# 2. FCA da CVM: ações ativas em bolsa (ticker -> CNPJ, nome)
# ---------------------------------------------------------------------------
def _csv_valor_mobiliario(ano: int) -> list[dict]:
    res = requests.get(FCA_URL.format(ano=ano), timeout=60)
    if res.status_code == 404:
        return []
    res.raise_for_status()
    zf = zipfile.ZipFile(io.BytesIO(res.content))
    nome = next((n for n in zf.namelist() if "valor_mobiliario" in n.lower()), None)
    if not nome:
        return []
    linhas = [l for l in zf.read(nome).decode("latin-1").split("\n") if l.strip()]
    colunas = linhas[0].strip().split(";")
    return [dict(zip(colunas, l.strip().split(";"))) for l in linhas[1:]]


def ler_fca(ano_atual: int) -> tuple[dict[str, dict], set[str]]:
    """-> (ativos {ticker: {cnpj, nome, segmento_listagem}}, encerrados {ticker}).
    Junta o ano atual e o anterior (o arquivo do ano só tem quem já entregou
    o FCA daquele ano) e fica com a entrega mais recente de cada ticker.
    Colunas confirmadas em execução real (24/set): CNPJ_Companhia,
    Data_Referencia, Versao, Nome_Empresarial, Valor_Mobiliario,
    Codigo_Negociacao, Mercado, Data_Fim_Negociacao, Segmento."""
    por_ticker: dict[str, dict] = {}
    for ano in (ano_atual - 1, ano_atual):          # o mais novo sobrescreve
        for r in _csv_valor_mobiliario(ano):
            t = (r.get("Codigo_Negociacao") or "").strip().upper()
            if not t or (r.get("Mercado") or "").strip() != "Bolsa":
                continue
            chave = ((r.get("Data_Referencia") or ""), (r.get("Versao") or ""))
            atual = por_ticker.get(t)
            if atual is None or chave >= atual["_chave"]:
                por_ticker[t] = {"_chave": chave, "cnpj": r.get("CNPJ_Companhia"),
                                 "nome": r.get("Nome_Empresarial"),
                                 "segmento_listagem": r.get("Segmento"),
                                 "fim": (r.get("Data_Fim_Negociacao") or "").strip()}
    ativos = {t: v for t, v in por_ticker.items() if not v["fim"]}
    encerrados = {t for t, v in por_ticker.items() if v["fim"]}
    return ativos, encerrados


# ---------------------------------------------------------------------------
# 3. Montagem
# ---------------------------------------------------------------------------
def _num(v):
    try:
        f = float(v)
        return f if f == f else None   # descarta NaN
    except (TypeError, ValueError):
        return None


def _por_acao(snap: dict, campo_guardado: str, multiplo: str):
    """LPA/VPA: valor guardado; senão, identidade preço/múltiplo da última foto."""
    guardado = _num(snap.get(campo_guardado))
    if guardado:
        return guardado
    preco_antigo, mult = _num(snap.get("preco")), _num(snap.get(multiplo))
    if preco_antigo and mult:
        return preco_antigo / mult
    return None


def montar_listas(supabase_url: str, headers: dict, provedores=None, hoje: date | None = None,
                  workers: int = 8):
    """-> (acoes_data, fiis_data, relatorio). Levanta FalhaFonte se não der
    para montar uma carga confiável."""
    hoje = hoje or hoje_brasilia()
    provedores = provedores if provedores is not None else carregar_provedores()
    if not provedores:
        raise FalhaFonte("nenhum provedor de preço disponível (ver PROVEDORES_ORDEM e chaves)")

    snapshot = ler_snapshot(supabase_url, headers)
    if not snapshot:
        raise FalhaFonte("base atual vazia -- sem ela não há lista de FIIs nem fundamentos")
    exigir_colunas_lpa_vpa(snapshot)

    try:
        fca, encerrados = ler_fca(hoje.year)
    except Exception as e:  # FCA enriquece a lista; se falhar, segue só com a base
        print(f"AVISO: FCA da CVM indisponível ({type(e).__name__}: {e}); usando só a lista da base.")
        fca, encerrados = {}, set()

    acoes = sorted(({t for t, s in snapshot.items() if s.get("tipo") == "ACAO"} | set(fca)) - encerrados)
    fiis = sorted(t for t, s in snapshot.items() if s.get("tipo") == "FII")
    todos = acoes + fiis

    cotacoes, faltando, resumo = buscar_cotacoes(todos, provedores)
    cobertura = len(cotacoes) / len(todos) if todos else 0
    print(f"Cotações: {len(cotacoes)}/{len(todos)} ({cobertura:.0%}) por fonte {resumo}")
    if cobertura < COBERTURA_MINIMA:
        raise FalhaFonte(f"só {cobertura:.0%} dos ativos com preço (mínimo {COBERTURA_MINIMA:.0%}) "
                         "-- provável bloqueio das fontes. Nada será gravado.")

    desde = hoje - timedelta(days=400)
    def _prov(t):
        return t, buscar_proventos(t, desde, provedores)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        proventos = dict(ex.map(_prov, list(cotacoes)))

    sem_dy = 0
    acoes_data, fiis_data = [], []
    for t in todos:
        cot = cotacoes.get(t)
        if cot is None:
            continue                      # sem preço: fica fora; a linha antiga permanece
        snap = snapshot.get(t, {})
        lista, _fonte_prov = proventos.get(t, (None, None))
        dy = dy_12m(lista, cot.preco, hoje)
        sem_dy += dy is None
        comum = {"ticker": t, "price": cot.preco, "dy": dy,
                 "companyName": snap.get("nome") or (fca.get(t) or {}).get("nome") or t,
                 "liquidezmediadiaria": snap.get("liquidez_media_diaria"),
                 "_fonte_preco": cot.fonte}
        vpa = _por_acao(snap, "vpa", "p_vp")
        if t in fiis:
            fiis_data.append({**comum,
                "p_vp": cot.preco / vpa if vpa else None,
                "segment": str(snap.get("setor") or "").removeprefix("FII ").strip() or None,
                "vacanciafisica": snap.get("vacancia_fisica"),
                "vacanciafinanceira": snap.get("vacancia_financeira"),
                "_lpa": None, "_vpa": vpa})
        else:
            lpa = _por_acao(snap, "lpa", "p_l")
            acoes_data.append({**comum,
                "p_l": cot.preco / lpa if lpa else None,
                "p_vp": cot.preco / vpa if vpa else None,
                "sectorName": snap.get("setor"),          # ação nova do FCA: sem setor -> não é BEST
                "margembruta": snap.get("margem_bruta"),
                "margemliquida": snap.get("margem_liquida"),
                "roe": snap.get("roe"), "roic": snap.get("roic"),
                "_lpa": lpa, "_vpa": vpa})

    novas = sorted(set(acoes) - set(snapshot))
    relatorio = {"acoes": len(acoes_data), "fiis": len(fiis_data), "sem_preco": faltando,
                 "sem_dy": sem_dy, "fontes_preco": resumo, "acoes_novas_fca": novas,
                 "encerradas_fca": sorted(encerrados & set(snapshot))}
    print(f"Montado: {len(acoes_data)} ações, {len(fiis_data)} FIIs; {sem_dy} sem proventos informados "
          f"(DY desconhecido); {len(novas)} ações novas vindas do FCA; "
          f"{len(relatorio['encerradas_fca'])} encerradas segundo o FCA (fora da carga).")
    return acoes_data, fiis_data, relatorio
