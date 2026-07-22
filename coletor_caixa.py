#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
========================================================================
 COLETOR CAIXA — Busca Leilões
========================================================================
O que ele faz:
  Baixa as listas PÚBLICAS de imóveis da Caixa Econômica Federal
  (uma por estado), lê cada linha e gera um arquivo `dados.json`
  no formato que a nossa página entende — com LINK DIRETO de cada imóvel.

Fonte oficial (aberta ao público):
  https://venda-imoveis.caixa.gov.br/listaweb/Lista_imoveis_<UF>.csv

Como rodar (no servidor ou no seu PC):
  pip install requests
  python coletor_caixa.py
Resultado:
  gera/atualiza o arquivo  dados.json  na mesma pasta.

Observação: a Caixa NÃO fornece as fotos nesse arquivo. O link leva à
página oficial do imóvel, onde ficam as fotos e o edital. Por isso os
imóveis da Caixa entram sem foto (mostram um ícone) — mas com link real.
========================================================================
"""

import csv
import io
import json
import sys
from datetime import datetime

try:
    import requests
except ImportError:
    print("Falta a biblioteca 'requests'. Rode:  pip install requests")
    sys.exit(1)

UFS = ["AC","AL","AP","AM","BA","CE","DF","ES","GO","MA","MT","MS","MG",
       "PA","PB","PR","PE","PI","RJ","RN","RS","RO","RR","SC","SP","SE","TO"]

URL = "https://venda-imoveis.caixa.gov.br/listaweb/Lista_imoveis_{uf}.csv"
HEADERS = {"User-Agent": "Mozilla/5.0 (compativel; BuscaLeiloes/1.0)"}

# Mapeia a "Descrição" da Caixa para um tipo simples da nossa página
def classificar_tipo(descricao: str) -> str:
    d = (descricao or "").lower()
    if "apart" in d or "apto" in d:          return "Apartamento"
    if "casa" in d or "sobrado" in d:        return "Casa"
    if "terreno" in d or "lote" in d or "gleba" in d: return "Terreno"
    if "loja" in d or "sala" in d or "comerc" in d or "prédio" in d or "galp" in d: return "Comercial"
    if "rural" in d or "fazenda" in d or "sítio" in d or "chácara" in d: return "Rural"
    return "Imóvel"

def brl_para_numero(txt: str):
    """'150.000,00' -> 150000.0  (retorna None se vazio)"""
    if not txt:
        return None
    t = txt.strip().replace("R$", "").replace(".", "").replace(",", ".").strip()
    try:
        return float(t)
    except ValueError:
        return None

def achar_cabecalho(linhas):
    """A Caixa põe um título nas primeiras linhas; o cabeçalho real é a
    linha que contém 'N° do imóvel' (ou 'Link de acesso')."""
    for i, ln in enumerate(linhas):
        low = ln.lower()
        if "imóvel" in low and ("link" in low or "endereço" in low):
            return i
    return 0

def parse_csv(texto: str, uf: str):
    """Recebe o TEXTO do CSV da Caixa e devolve a lista de lotes no nosso
    formato. Separado do download para poder ser testado sem internet."""
    linhas = texto.splitlines()
    if not linhas:
        return []

    idx = achar_cabecalho(linhas)
    corpo = "\n".join(linhas[idx:])
    leitor = csv.DictReader(io.StringIO(corpo), delimiter=";")

    lotes = []
    for row in leitor:
        # Normaliza os nomes das colunas (tira espaços/acentos variáveis).
        # Obs.: quando uma linha tem MAIS colunas que o cabeçalho (endereço com ';'
        # ou coluna extra), o DictReader junta o excedente numa lista sob a chave
        # None — por isso tratamos valores que vêm como lista.
        campos = {}
        for k, v in row.items():
            chave = (k or "").strip().lower()
            if isinstance(v, list):
                v = " ".join(x for x in v if x)
            campos[chave] = (v or "").strip()

        def pega(*nomes):
            for n in nomes:
                for chave in campos:
                    if n in chave:
                        return campos[chave]
            return ""

        endereco  = pega("endereço", "endereco")
        cidade    = pega("cidade")
        bairro    = pega("bairro")
        preco     = brl_para_numero(pega("preço", "preco"))
        avaliacao = brl_para_numero(pega("avalia"))
        descricao = pega("descri")
        modalidade= pega("modalidade") or "Venda Direta"
        link      = pega("link", "acesso")
        numero    = pega("n° do imóvel", "imóvel", "imovel")

        if not link or preco is None:
            continue

        titulo = descricao or f"Imóvel {numero}"
        if bairro:
            titulo = f"{titulo} — {bairro}"

        lotes.append({
            "cat": "imovel",
            "tipo": classificar_tipo(descricao),
            "titulo": titulo.strip(" —"),
            "cidade": cidade or "-",
            "uf": uf,
            "endereco": endereco,
            "preco": preco,
            "avaliacao": avaliacao,
            "modalidade": modalidade,
            "fonte": "Caixa",
            "url": link,
            "fotos": [],           # a Caixa não traz foto no arquivo
            "real": True,
            "coletadoEm": datetime.now().strftime("%Y-%m-%d"),
        })
    return lotes

def coletar_uf(uf: str):
    """Baixa o CSV da Caixa para uma UF e devolve os lotes."""
    url = URL.format(uf=uf)
    try:
        r = requests.get(url, headers=HEADERS, timeout=60)
        r.raise_for_status()
    except Exception as e:
        print(f"  [{uf}] erro ao baixar: {e}")
        return []
    # A Caixa usa encoding latin-1 (ISO-8859-1) e separador ';'
    texto = r.content.decode("latin-1", errors="replace")
    lotes = parse_csv(texto, uf)
    print(f"  [{uf}] {len(lotes)} imóveis")
    return lotes

def main():
    print("Coletando imóveis da Caixa (todas as UFs)...")
    todos = []
    for uf in UFS:
        todos.extend(coletar_uf(uf))

    saida = {
        "atualizadoEm": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "totalLotes": len(todos),
        "fontes": ["Caixa"],
        "lotes": todos,
    }
    with open("dados.json", "w", encoding="utf-8") as f:
        json.dump(saida, f, ensure_ascii=False, indent=1)

    print(f"\nPronto! {len(todos)} imóveis salvos em dados.json")

if __name__ == "__main__":
    main()
