"""valida_fca.py -- VALIDAÇÃO (não é produção).

Pergunta a responder: o Formulário Cadastral (FCA) da CVM traz o código de
negociação (ticker) ligado ao CNPJ da empresa? Se sim, ele substitui o
Status Invest como LISTA DE ATIVOS e como ELO ticker -> CNPJ -> DFP.

Fonte (confirmada no portal, atualização semanal):
  https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/FCA/DADOS/fca_cia_aberta_{ano}.zip
  arquivo interno esperado: fca_cia_aberta_valor_mobiliario_{ano}.csv
  (Seção 2 do formulário -- valores mobiliários)

NÃO SEI os nomes das colunas. Este script imprime as colunas reais e as
linhas de uma empresa de teste, para decidirmos com o dado na mão.

Uso:  python valida_fca.py            (busca PETROBRAS e PETR)
      python valida_fca.py TAESA TAEE
"""
import io
import sys
import zipfile
from datetime import date

import requests

URL = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/FCA/DADOS/fca_cia_aberta_{ano}.zip"


def baixar(ano):
    for a in (ano, ano - 1):
        url = URL.format(ano=a)
        print(f"Baixando {url} ...")
        r = requests.get(url, timeout=60)
        if r.status_code == 404:
            print("  404, tentando o ano anterior")
            continue
        r.raise_for_status()
        print(f"  -> {len(r.content) / 1000:.0f} KB")
        return zipfile.ZipFile(io.BytesIO(r.content)), a
    raise SystemExit("Nenhum ano disponível.")


def main():
    termo_nome = (sys.argv[1] if len(sys.argv) > 1 else "PETROBRAS").upper()
    termo_ticker = (sys.argv[2] if len(sys.argv) > 2 else "PETR").upper()
    zf, ano = baixar(date.today().year)

    print("\nArquivos no ZIP:")
    for n in zf.namelist():
        print(f"  {n}")

    alvo = next((n for n in zf.namelist() if "valor_mobiliario" in n.lower()), None)
    if not alvo:
        raise SystemExit("\nArquivo de valor mobiliário não encontrado -- veja a lista acima.")

    texto = zf.read(alvo).decode("latin-1")
    linhas = [l for l in texto.split("\n") if l.strip()]
    sep = ";" if ";" in linhas[0] else ","
    colunas = linhas[0].strip().split(sep)
    print(f"\n[{alvo}] {len(linhas) - 1} linhas, separador {sep!r}")
    print(f"Colunas ({len(colunas)}):")
    for i, c in enumerate(colunas):
        print(f"  {i:2d} {c}")

    achadas = [l for l in linhas[1:] if termo_nome in l.upper() or termo_ticker in l.upper()]
    print(f"\nLinhas contendo {termo_nome!r} ou {termo_ticker!r}: {len(achadas)} (mostrando até 15)")
    for l in achadas[:15]:
        campos = l.strip().split(sep)
        print("  ---")
        for c, v in zip(colunas, campos):
            if v.strip():
                print(f"    {c}: {v}")

    print("\nO que procurar acima: uma coluna com o CÓDIGO DE NEGOCIAÇÃO (ex. PETR4)\n"
          "na mesma linha do CNPJ. Se existir, é o elo oficial ticker -> CNPJ.")


if __name__ == "__main__":
    main()
