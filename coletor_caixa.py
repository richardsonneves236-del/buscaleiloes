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
import re
import sys
import time
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

def limpar_titulo(descricao: str, tipo: str, bairro: str) -> str:
    """Transforma a descrição gigante da Caixa num título curto:
    'Apartamento · 2 quartos · 46 m² — BAIRRO'."""
    d = descricao or ""
    partes = [tipo]
    mq = re.search(r"(\d+)\s*(?:qto|quarto|dorm)", d, re.I)
    if mq:
        partes.append(f"{mq.group(1)} quartos")
    ma = re.search(r"([\d.,]+)\s*de área privativa", d, re.I)
    if ma:
        try:
            a = float(ma.group(1).replace(".", "").replace(",", ".")) if "," in ma.group(1) else float(ma.group(1))
            if a > 0:
                partes.append(f"{a:.0f} m²")
        except ValueError:
            pass
    mv = re.search(r"(\d+)\s*vaga", d, re.I)
    if mv and mv.group(1) != "0":
        partes.append(f"{mv.group(1)} vaga(s)")
    titulo = " · ".join(partes)
    if bairro:
        titulo += f" — {bairro}"
    return titulo

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

        tipo = classificar_tipo(descricao)
        titulo = limpar_titulo(descricao, tipo, bairro)

        # Fotos: a Caixa nomeia as imagens como F + código com zeros à esquerda
        # (13 dígitos) + índice da foto. Ex.: código 10005120 -> F000001000512021.jpg
        # No site, se alguma não carregar, cai no ícone (sem imagem quebrada).
        cod = re.sub(r"\D", "", numero or "")
        fotos = []
        if cod:
            base = f"F{cod.zfill(13)}"
            fotos = [f"https://venda-imoveis.caixa.gov.br/fotos/{base}{i}.jpg" for i in (21, 22, 23)]

        lotes.append({
            "cat": "imovel",
            "tipo": tipo,
            "titulo": titulo.strip(" —"),
            "descricao": descricao,
            "numero": numero,
            "cidade": cidade or "-",
            "uf": uf,
            "endereco": endereco,
            "preco": preco,
            "avaliacao": avaliacao,
            "modalidade": modalidade,
            "fonte": "Caixa",
            "url": link,
            "fotos": fotos,
            "real": True,
            "coletadoEm": datetime.now().strftime("%Y-%m-%d"),
        })
    return lotes

# Uma sessão só (reaproveita cookies/conexão — ajuda com o servidor da Caixa)
SESSAO = requests.Session()
SESSAO.headers.update(HEADERS)

def coletar_uf(uf: str, tentativas: int = 6):
    """Baixa o CSV da Caixa para uma UF e devolve os lotes.
    A Caixa costuma 'segurar' requisições rápidas em sequência, então
    tentamos várias vezes com pausa crescente e diagnóstico se vier vazio."""
    url = URL.format(uf=uf)
    for t in range(tentativas):
        espera = 3 * (t + 1)  # backoff crescente: 3, 6, 9, 12, 15s...
        try:
            r = SESSAO.get(url, timeout=90)
            r.raise_for_status()
        except Exception as e:
            print(f"  [{uf}] erro ao baixar (tentativa {t+1}): {e}")
            time.sleep(espera)
            continue
        # A Caixa usa encoding latin-1 (ISO-8859-1) e separador ';'
        texto = r.content.decode("latin-1", errors="replace")
        lotes = parse_csv(texto, uf)
        if lotes:
            print(f"  [{uf}] {len(lotes)} imóveis")
            return lotes
        # Veio 0: mostra o que chegou para diagnosticar, e tenta de novo
        amostra = texto[:120].replace("\n", " ").replace("\r", " ")
        print(f"  [{uf}] 0 (tentativa {t+1}, status={r.status_code}, bytes={len(r.content)}, inicio={amostra!r})")
        time.sleep(espera)
    return []

def carregar_previo():
    """Lê o dados.json anterior e agrupa os lotes por UF, para não perder
    dados de um estado se a Caixa bloquear justamente aquela requisição hoje."""
    try:
        with open("dados.json", encoding="utf-8") as f:
            data = json.load(f)
        prev = {}
        for l in data.get("lotes", []):
            prev.setdefault(l.get("uf"), []).append(l)
        return prev
    except Exception:
        return {}

def main():
    print("Coletando imóveis da Caixa (todas as UFs)...")
    prev = carregar_previo()
    todos = []
    for uf in UFS:
        lotes = coletar_uf(uf)
        if not lotes and prev.get(uf):
            lotes = prev[uf]
            print(f"  [{uf}] 0 agora — mantendo {len(lotes)} da coleta anterior")
        todos.extend(lotes)
        time.sleep(1.5)  # pausa educada entre estados

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
