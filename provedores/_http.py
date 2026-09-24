"""GET com tratamento de erro uniforme para os plugues HTTP."""
from __future__ import annotations

import requests

from .base import ErroProvedor


def get_json(url: str, *, params=None, headers=None, timeout=30, rotulo=""):
    try:
        res = requests.get(url, params=params, headers=headers, timeout=timeout)
    except requests.RequestException as e:
        raise ErroProvedor(f"{rotulo}: erro de rede ({e})") from e
    if res.status_code in (401, 403):
        raise ErroProvedor(f"{rotulo}: acesso negado (HTTP {res.status_code}) -- chave ausente, "
                           f"inválida ou plano sem acesso. Início: {res.text[:150]!r}")
    if res.status_code == 429:
        raise ErroProvedor(f"{rotulo}: limite de requisições atingido (HTTP 429)")
    if not (200 <= res.status_code < 300):
        raise ErroProvedor(f"{rotulo}: HTTP {res.status_code}. Início: {res.text[:150]!r}")
    try:
        return res.json()
    except ValueError as e:
        raise ErroProvedor(f"{rotulo}: resposta não é JSON. Início: {res.text[:150]!r}") from e


def em_lotes(itens: list, tamanho: int):
    for i in range(0, len(itens), max(1, tamanho)):
        yield itens[i:i + tamanho]


def data_iso(texto):
    """'2026-08-31T03:00:00.000Z' -> date. None se vazio/ inválido."""
    from datetime import datetime
    if not texto:
        return None
    try:
        return datetime.fromisoformat(str(texto).replace("Z", "+00:00")).date()
    except ValueError:
        return None
