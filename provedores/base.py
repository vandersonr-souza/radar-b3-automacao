"""Contrato comum a todos os provedores. Nenhum provedor devolve formato
próprio: tudo sai como Cotacao/Provento, sempre com o campo `fonte`."""
from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime


class ErroProvedor(Exception):
    """Falha do provedor como um todo (rede, chave inválida, formato
    inesperado). Falha de UM ticker não levanta exceção: o ticker só fica
    de fora do resultado e o agregador tenta o próximo provedor."""


@dataclass(frozen=True)
class Cotacao:
    ticker: str
    preco: float
    fonte: str
    momento: datetime | None = None   # horário do preço informado pela fonte, se houver

    def __post_init__(self):
        if not isinstance(self.preco, (int, float)) or not math.isfinite(self.preco) or self.preco <= 0:
            raise ValueError(f"{self.ticker}: preço inválido {self.preco!r} (fonte {self.fonte})")


@dataclass(frozen=True)
class Provento:
    ticker: str
    valor_por_acao: float
    data_ex: date                 # data que define a janela de 12 meses do DY
    fonte: str
    tipo: str = ""                # "DIVIDENDO", "JCP", "RENDIMENTO"... como a fonte informar
    data_pagamento: date | None = None


def normalizar_ticker(t: str) -> str:
    return t.strip().upper().removesuffix(".SA")


class ProvedorMercado(ABC):
    """Todo plugue herda daqui.

    nome        -- identificador usado na configuração (PROVEDORES_ORDEM)
    requer_chave-- só documentação; quem decide é disponivel()
    """
    nome: str = "base"
    requer_chave: bool = False

    def disponivel(self) -> tuple[bool, str]:
        """(True, "") se pode ser usado; (False, motivo) se não. Ex.: falta
        a variável de ambiente da chave, ou a biblioteca não está instalada."""
        return True, ""

    @abstractmethod
    def cotacoes(self, tickers: list[str]) -> dict[str, Cotacao]:
        """Devolve só os tickers que conseguiu. Ticker ausente = não coberto."""

    def proventos(self, ticker: str, desde: date) -> list[Provento] | None:
        """Lista de proventos com data_ex >= desde.
        None  = este provedor NÃO sabe informar proventos (não é 'zero').
        []    = sabe informar e não há registro no período."""
        return None

    def serie_precos(self, ticker: str) -> list[tuple] | None:
        """[(data, fechamento), ...] do histórico já baixado, se o provedor
        tiver. None = não informa. Usado na regularidade de 3 anos (Bazin)."""
        return None
