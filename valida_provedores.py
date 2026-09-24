"""valida_provedores.py -- VALIDAÇÃO com rede real (não é produção).

Consulta CADA provedor disponível separadamente para os mesmos tickers e
mostra lado a lado: preço, nº de proventos em 12 meses, DY calculado e a
divergência entre fontes. Serve para decidir a ordem da cascata com dado
real, não com suposição.

Uso:
    python valida_provedores.py                      (tickers de teste)
    python valida_provedores.py PETR4 HGLG11 TAEE11
Chaves opcionais (variáveis de ambiente): BRAPI_TOKEN, HGBRASIL_KEY.
Sem BRAPI_TOKEN a brapi só responde PETR4, VALE3, MGLU3 e ITUB4.
"""
import sys
from datetime import date, timedelta

from provedores import REGISTRO, dy_12m

TESTE = ["PETR4", "VALE3", "ITUB4", "MGLU3", "HGLG11"]


def main():
    tickers = [t.upper() for t in sys.argv[1:]] or TESTE
    hoje = date.today()
    desde = hoje - timedelta(days=400)
    provs = []
    for nome, cls in REGISTRO.items():
        p = cls()
        ok, motivo = p.disponivel()
        print(f"{nome:10s} {'ATIVO' if ok else 'IGNORADO'} {('-- ' + motivo) if motivo else ''}")
        if ok:
            provs.append(p)
    if not provs:
        print("Nenhum provedor disponível."); sys.exit(1)

    tabela = {t: {} for t in tickers}
    for p in provs:
        print(f"\nConsultando {p.nome}...")
        try:
            cot = p.cotacoes(tickers)
        except Exception as e:
            print(f"  falhou: {type(e).__name__}: {e}"); cot = {}
        for t in tickers:
            c = cot.get(t)
            pv = p.proventos(t, desde) if c else None
            tabela[t][p.nome] = (c.preco if c else None,
                                 None if pv is None else len([x for x in pv if x.data_ex > hoje - timedelta(days=365)]),
                                 dy_12m(pv, c.preco, hoje) if c else None)

    fmt = lambda v, f: "-" if v is None else f.format(v)
    print("\n" + "=" * 72)
    print(f"{'TICKER':8s} {'FONTE':10s} {'PREÇO':>10s} {'PROV.12m':>9s} {'DY 12m %':>9s}")
    print("=" * 72)
    for t in tickers:
        precos = [v[0] for v in tabela[t].values() if v[0]]
        for nome, (preco, n, dy) in tabela[t].items():
            print(f"{t:8s} {nome:10s} {fmt(preco, '{:>10.2f}'):>10s} {fmt(n, '{:>9d}'):>9s} {fmt(dy, '{:>9.2f}'):>9s}")
        if len(precos) > 1:
            div = (max(precos) - min(precos)) / min(precos) * 100
            alerta = "  <-- ATENÇÃO" if div > 2 else ""
            print(f"{'':8s} divergência de preço entre fontes: {div:.2f}%{alerta}")
        print("-" * 72)
    print("PROV.12m '-' = a fonte não informa proventos (não significa zero).\n"
          "Confira DY e proventos de 1 ou 2 tickers contra o site de RI da empresa\n"
          "antes de escolher a ordem da cascata (PROVEDORES_ORDEM).")


if __name__ == "__main__":
    main()
