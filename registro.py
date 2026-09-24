"""Registro de plugues. PARA ADICIONAR UMA FONTE NOVA:
  1. crie um arquivo com uma classe que herda de ProvedorMercado;
  2. acrescente-a em REGISTRO abaixo;
  3. inclua o nome dela em PROVEDORES_ORDEM (variável de ambiente).
Nada mais no coletor precisa mudar."""
from __future__ import annotations

import os

from .brapi import BrapiProvedor
from .hgbrasil import HGBrasilProvedor
from .yfinance_prov import YFinanceProvedor

REGISTRO = {
    "brapi": BrapiProvedor,
    "yfinance": YFinanceProvedor,
    "hgbrasil": HGBrasilProvedor,
}

# yfinance primeiro (24/set): cobre em massa e grátis; a brapi gratuita aceita
# só 1 ativo por requisição e fica como reserva do que faltar.
ORDEM_PADRAO = "yfinance,brapi,hgbrasil"


def carregar_provedores(ordem: str | None = None, verbose: bool = True):
    """Instancia os provedores na ordem pedida, pulando os indisponíveis
    (sem chave, lib ausente) com o motivo no log. Nome desconhecido na
    configuração é erro explícito, não ignorado em silêncio."""
    ordem = ordem or os.environ.get("PROVEDORES_ORDEM", ORDEM_PADRAO)
    nomes = [n.strip().lower() for n in ordem.split(",") if n.strip()]
    desconhecidos = [n for n in nomes if n not in REGISTRO]
    if desconhecidos:
        raise ValueError(f"Provedor(es) desconhecido(s) em PROVEDORES_ORDEM: {desconhecidos}. "
                         f"Disponíveis: {sorted(REGISTRO)}")
    ativos = []
    for n in nomes:
        prov = REGISTRO[n]()
        ok, motivo = prov.disponivel()
        if ok:
            ativos.append(prov)
            if verbose and motivo:
                print(f"  provedor {n}: ativo ({motivo})")
        elif verbose:
            print(f"  provedor {n}: IGNORADO -- {motivo}")
    return ativos
