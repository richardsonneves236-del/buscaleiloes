#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
========================================================================
 ANÁLISE DE IA DO EDITAL — Busca Leilões (Google Gemini, plano gratuito)
========================================================================
O que faz:
  1. Lê o dados.json gerado pelo coletor.
  2. Escolhe os MELHORES lotes (maior score de oportunidade).
  3. Para cada um, abre a página oficial do imóvel na Caixa e lê o texto.
  4. Manda pro Gemini, que devolve: resumo, ocupação, dívidas/ônus,
     financiamento/FGTS, riscos e um veredito.
  5. Grava a análise dentro de cada lote (campo "ia") no dados.json.

Custo: usa o plano GRATUITO do Gemini (Google AI Studio). Rodando só nos
melhores lotes por dia, fica bem dentro do limite gratuito.

Como ativar:
  - Crie uma chave gratuita em https://aistudio.google.com/app/apikey
  - No GitHub: Settings > Secrets and variables > Actions > New repository secret
    Nome: GEMINI_API_KEY   Valor: (sua chave)
  - Pronto. Se a chave não existir, este script não faz nada (não quebra o robô).

Config por variáveis de ambiente (opcionais):
  GEMINI_API_KEY  -> a chave (obrigatória para funcionar)
  GEMINI_MODEL    -> modelo (padrão: gemini-2.0-flash)
  MAX_IA          -> quantos lotes analisar por rodada (padrão: 40)
========================================================================
"""

import json
import os
import re
import sys
import time

try:
    import requests
except ImportError:
    print("Falta 'requests'. Rode: pip install requests")
    sys.exit(0)

API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
MODEL = os.environ.get("GEMINI_MODEL", "").strip()  # vazio = descobre sozinho
MAX_IA = int(os.environ.get("MAX_IA", "40"))
BASE = "https://generativelanguage.googleapis.com/v1beta"
HEADERS = {"User-Agent": "Mozilla/5.0 (compativel; BuscaLeiloes/1.0)"}


def descobrir_modelo():
    """Pergunta ao Gemini quais modelos existem e escolhe um Flash válido.
    Assim não quebra quando o Google renomeia os modelos."""
    try:
        r = requests.get(f"{BASE}/models", params={"key": API_KEY}, timeout=30)
        r.raise_for_status()
        nomes = []
        for m in r.json().get("models", []):
            if "generateContent" in m.get("supportedGenerationMethods", []):
                nm = m["name"].split("/")[-1]
                low = nm.lower()
                if "flash" in low and "embedding" not in low and "vision" not in low:
                    nomes.append(nm)

        def rank(n):
            n = n.lower()
            return ("exp" in n or "preview" in n, "thinking" in n, "lite" in n, "8b" in n, n)

        nomes.sort(key=rank)
        if nomes:
            return nomes[0]
        print("  (nenhum modelo Flash encontrado na conta)")
    except Exception as e:
        print(f"  (não consegui listar modelos: {e})")
    return None

MARCAS_LIQUIDAS = ["Toyota", "Honda", "Volkswagen", "Chevrolet", "Hyundai", "Jeep", "Fiat", "Yamaha"]


def score(l):
    """Mesma lógica do site, para escolher os melhores lotes."""
    nota = 48
    av = l.get("avaliacao")
    if av:
        d = 1 - l["preco"] / av
        if d >= 0.45: nota += 30
        elif d >= 0.30: nota += 20
        elif d >= 0.15: nota += 11
        elif d > 0: nota += 4
    m = (l.get("modalidade") or "").lower()
    if l.get("cat") == "veiculo" and l.get("marca") in MARCAS_LIQUIDAS:
        nota += 8
    if "judicial" in m or "sfi" in m:
        nota -= 7
    elif "venda direta" in m or "venda online" in m:
        nota += 5
    return nota


def texto_da_pagina(url):
    """Baixa a página do imóvel e devolve o texto limpo (sem HTML)."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=45)
        r.raise_for_status()
    except Exception as e:
        print(f"    (erro ao abrir página: {e})")
        return ""
    html = r.content.decode("latin-1", errors="replace")
    html = re.sub(r"(?is)<script.*?</script>", " ", html)
    html = re.sub(r"(?is)<style.*?</style>", " ", html)
    txt = re.sub(r"(?is)<[^>]+>", " ", html)
    txt = re.sub(r"&nbsp;", " ", txt)
    txt = re.sub(r"\s+", " ", txt).strip()
    return txt[:6000]


def analisar_com_gemini(lote, texto):
    prompt = (
        "Você é um analista especialista em leilões de imóveis da Caixa no Brasil. "
        "Com base APENAS no texto da página oficial do imóvel abaixo, responda de forma objetiva e honesta. "
        "Se alguma informação não estiver no texto, responda 'Não informado' — não invente.\n\n"
        f"IMÓVEL: {lote.get('titulo','')} — {lote.get('cidade','')}/{lote.get('uf','')} — "
        f"preço R$ {lote.get('preco','')} (avaliação R$ {lote.get('avaliacao','')}).\n\n"
        f"TEXTO DA PÁGINA:\n{texto}\n\n"
        "Responda em JSON com exatamente estes campos:\n"
        "{\n"
        '  "resumo": "2 a 3 frases sobre o imóvel e a oportunidade",\n'
        '  "ocupacao": "Ocupado" ou "Desocupado" ou "Não informado",\n'
        '  "dividas": "resumo de IPTU/condomínio/ônus e quem paga, ou Não informado",\n'
        '  "financiamento": "Sim" ou "Não" ou "Não informado (aceita financiamento/FGTS?)",\n'
        '  "riscos": ["lista curta de pontos de atenção reais"],\n'
        '  "veredito": "1 frase: para quem essa oportunidade faz sentido e por quê"\n'
        "}"
    )
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"},
    }
    url = f"{BASE}/models/{MODEL}:generateContent"
    r = requests.post(url, params={"key": API_KEY}, json=body, timeout=90)
    r.raise_for_status()
    data = r.json()
    txt = data["candidates"][0]["content"]["parts"][0]["text"]
    return json.loads(txt)


def main():
    global MODEL
    if not API_KEY:
        print("GEMINI_API_KEY não definido — pulando análise de IA (isso é normal até você adicionar a chave).")
        return

    if not MODEL:
        MODEL = descobrir_modelo()
    if not MODEL:
        print("Não encontrei um modelo Gemini válido — pulando análise de IA.")
        return
    print(f"Modelo Gemini em uso: {MODEL}")

    try:
        with open("dados.json", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"Não consegui ler dados.json: {e}")
        return

    lotes = data.get("lotes", [])
    if not lotes:
        print("dados.json sem lotes.")
        return

    # Escolhe os melhores lotes que ainda não têm análise
    candidatos = sorted(lotes, key=score, reverse=True)
    alvo = [l for l in candidatos if not l.get("ia")][:MAX_IA]
    print(f"Analisando {len(alvo)} lotes com IA (modelo {MODEL})...")

    feitos = 0
    for l in alvo:
        titulo = l.get("titulo", "?")
        texto = texto_da_pagina(l.get("url", ""))
        if not texto:
            continue
        try:
            l["ia"] = analisar_com_gemini(l, texto)
            feitos += 1
            print(f"  [{feitos}] {titulo[:50]} — ok")
        except Exception as e:
            print(f"  falha em '{titulo[:40]}': {e}")
        time.sleep(4.5)  # respeita o limite do plano gratuito (~15/min)

    data["iaAtualizadoEm"] = data.get("atualizadoEm", "")
    with open("dados.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print(f"Pronto! {feitos} análises de IA gravadas em dados.json")


if __name__ == "__main__":
    main()
