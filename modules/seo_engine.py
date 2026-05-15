"""
modules/seo_engine.py — Motor de SEO de Elite.

Monta o pacote completo de metadados sem alucinação:
  1. Título: Autocomplete real (YouTube Suggest API) → sem IA no título
  2. Sinopse: Reescrita pelo Gemini com prompt restrito
  3. Tags visíveis: Hashtags injetadas no fim da descrição
  4. Tags invisíveis: Passadas no campo 'tags' da API Dailymotion
  5. Template final: Blocos Zona Humana + Zona de Algoritmo (3000 chars)
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Optional

import httpx
from google import genai
from google.genai import types

from core.config import config
from core import database as db
from modules.scraper import extract_title_from_caption, clean_title

logger = logging.getLogger(__name__)

# Configura cliente Gemini (SDK nova) — usa v1beta para modelos gemini-3+
_gemini_client = genai.Client(
    api_key=config.gemini.api_key,
    http_options={"api_version": "v1beta"},
)
_GEMINI_MODEL = "gemini-3.1-flash-lite-preview"

# Limit total de chars da descrição Dailymotion
DM_DESC_LIMIT = 3000

def get_dynamic_triggers(caption: str) -> list[str]:
    """
    Analisa a legenda original para saber se o vídeo atual é Dublado ou Legendado.
    Regra do usuário: Se diz 'legendado' mas tem um link de redirecionamento, a versão atual é DUBLADA.
    Se não referenciar nada, ou não especificar, a versão atual é LEGENDADA.
    """
    caption_lower = caption.lower()
    is_dubbed = False
    
    if "dublado" in caption_lower:
        is_dubbed = True
        
    # Se a legenda menciona a versão legendada em um link, o vídeo atual é dublado!
    if "legendad" in caption_lower:
        if "http" in caption_lower or "t.me" in caption_lower or "@" in caption_lower or "link" in caption_lower:
            is_dubbed = True
        else:
            is_dubbed = False

    if is_dubbed:
        return ["🔥 DUBLADO:", "🎬 COMPLETO DUBLADO:", "🍿 NOVO DUBLADO:"]
    else:
        return ["🎬 LEGENDADO:", "📺 COMPLETO LEGENDADO:", "🍿 NOVO LEGENDADO:"]

# ------------------------------------------------------------------ #
#  1. Autocomplete de Título (YouTube Suggest)
# ------------------------------------------------------------------ #

async def fetch_autocomplete(title_base: str, max_results: int = 5) -> list[str]:
    """
    Consulta a API de sugestões do YouTube para capturar os termos
    mais buscados relacionados ao título base. Zero IA envolvida.
    """
    url = "https://suggestqueries.google.com/complete/search"
    params = {"q": title_base, "client": "youtube", "hl": "pt-BR", "gl": "BR"}

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url, params=params)
            r.raise_for_status()
            # Resposta é JSONP: )]}'\n[...]
            text = r.text
            # Remove callback wrapper
            match = re.search(r"\[.*\]", text, re.DOTALL)
            if not match:
                return []
            data = json.loads(match.group(0))
            suggestions = data[1] if len(data) > 1 else []
            # Cada sugestão é [termo, tipo, ...]
            terms = [s[0] for s in suggestions[:max_results] if isinstance(s, list)]
            logger.debug("[SEO] Autocomplete para '%s': %s", title_base, terms)
            return terms
    except Exception as e:
        logger.warning("[SEO] Falha no autocomplete: %s", e)
        return []


def pick_best_complement(title_base: str, suggestions: list[str], is_dubbed: bool = False) -> str:
    """
    Extrai o COMPLEMENTO relevante da melhor sugestão.
    Ex: 'Ouvi Pensamentos Dele e me Vinguei dublado completo' → 'Dublado Completo'
    """
    title_lower = title_base.lower()
    for suggestion in suggestions:
        # Remove o título base para pegar só o complemento
        complement = suggestion.lower().replace(title_lower, "").strip()
        if len(complement) > 3:
            return complement.title()
            
    # Fallback padrão baseado no status
    return "Dublado Completo" if is_dubbed else "Legendado Completo"


def build_seo_title(title_base: str, complement: str, trigger: str) -> str:
    """
    Monta o título SEO seguindo a estrutura rígida da documentação:
    [Gatilho de Status] + [Título Base Congelado] + [Complemento do Autocomplete]
    """
    title = f"{trigger} {title_base} - {complement}"
    # Dailymotion limita títulos a 255 chars
    return title[:255]


async def generate_title_variants(title_base: str, caption: str) -> list[str]:
    """Gera 3 variações de título usando diferentes gatilhos e complementos baseados no status."""
    triggers = get_dynamic_triggers(caption)
    is_dubbed = "DUBLADO" in triggers[0]
    
    suggestions = await fetch_autocomplete(title_base)
    complement = pick_best_complement(title_base, suggestions, is_dubbed)

    variants = []
    for trigger in triggers[:3]:
        variants.append(build_seo_title(title_base, complement, trigger))
    return variants


# ------------------------------------------------------------------ #
#  2. Sinopse Reescrita pelo Gemini
# ------------------------------------------------------------------ #

_SYNOPSIS_PROMPT = """Você é um copywriter especialista em conteúdo de mini-dramas.
Sua missão é melhorar a sinopse abaixo de forma magnética para o Dailymotion.

REGRAS ABSOLUTAS:
1. Mantenha os nomes dos personagens exatamente como estão.
2. NÃO altere o título da obra: "{titulo}"
3. Escreva um gancho emocional forte e desenvolva a trama mantendo o suspense.
4. OBRIGATÓRIO: Você NÃO PODE EXCLUIR os links, créditos, avisos, ou mensagens administrativas presentes no texto original. Tudo o que for "informação técnica/link" deve ser preservado intacto OBRIGATORIAMENTE abaixo da sinopse (apenas remova eventuais tags/hashtags soltas no final).
5. Escreva em português brasileiro fluente.

SINOPSE ORIGINAL:
{sinopse_original}

Escreva apenas a sinopse reescrita e as informações técnicas preservadas:"""


async def rewrite_synopsis(titulo: str, sinopse_original: str) -> str:
    """Chama o Gemini para reescrever a sinopse com prompt restrito."""
    if not sinopse_original:
        return "Uma história de amor, poder e vingança que vai te prender do início ao fim."

    prompt = _SYNOPSIS_PROMPT.format(titulo=titulo, sinopse_original=sinopse_original)

    try:
        response = await asyncio.to_thread(
            _gemini_client.models.generate_content,
            model=_GEMINI_MODEL,
            contents=prompt,
        )
        return response.text.strip()
    except Exception as e:
        logger.warning("[SEO] Falha no Gemini (sinopse): %s", e)
        return sinopse_original  # Fallback: usa sinopse original


# ------------------------------------------------------------------ #
#  3. Geração de Tags e Hashtags
# ------------------------------------------------------------------ #

_TAGS_PROMPT = """Com base no título "{titulo}" e na sinopse abaixo, gere dois blocos:

BLOCO 1 — HASHTAGS VISÍVEIS (3 a 5 hashtags):
Palavras-chave unidas com #, em português, relevantes para algoritmo do Dailymotion.
Formato: #MiniDrama #Romance #Vingança

BLOCO 2 — TAGS INVISÍVEIS (15 a 20 tags):
Lista separada por vírgula, sem #, em português e inglês misturando.
Formato: mini drama, dorama dublado, romance CEO, c drama

SINOPSE:
{sinopse}

Responda APENAS com os dois blocos no formato exato acima."""


async def generate_tags(titulo: str, sinopse: str) -> dict:
    """
    Retorna dict com:
      - hashtags: string de hashtags para o fim da descrição
      - tags: string de tags separadas por vírgula para campo 'tags' da API
    """
    prompt = _TAGS_PROMPT.format(titulo=titulo, sinopse=sinopse[:500])

    try:
        response = await asyncio.to_thread(
            _gemini_client.models.generate_content,
            model=_GEMINI_MODEL,
            contents=prompt,
        )
        text = response.text

        # Parse simples dos blocos
        hashtags = ""
        tags_invisible = ""

        lines = text.split("\n")
        current_block = None
        for line in lines:
            line = line.strip()
            if "BLOCO 1" in line or "HASHTAGS" in line:
                current_block = "hashtags"
                continue
            elif "BLOCO 2" in line or "TAGS INVISÍVEIS" in line or "INVISÍVEIS" in line:
                current_block = "tags"
                continue
            elif line and current_block == "hashtags" and line.startswith("#"):
                hashtags = line
            elif line and current_block == "tags" and not line.startswith("#"):
                tags_invisible = line

        return {
            "hashtags": hashtags or "#MiniDrama #DramaDublado #CDrama #Romance",
            "tags": tags_invisible or "mini drama, dorama dublado, cdrama, romance, drama asiatico",
        }

    except Exception as e:
        logger.warning("[SEO] Falha no Gemini (tags): %s", e)
        return {
            "hashtags": "#MiniDrama #DramaDublado #CDrama #Romance #Vingança",
            "tags": "mini drama, dorama dublado, cdrama romance, drama asiatico, novela chinesa",
        }


# ------------------------------------------------------------------ #
#  4. Template Final (Zona Humana + Zona de Algoritmo)
# ------------------------------------------------------------------ #

_DESCRIPTION_TEMPLATE = """{titulo_seo}

📝 A História:
{sinopse_reescrita}

📌 Ficha Técnica:
🎭 Gêneros: {generos}
⏱️ Duração: {duracao}

{hashtags}
🔔 Inscreva-se no canal para receber os melhores mini-dramas dublados!

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{zona_algoritmo}"""

_ALGORITMO_ZONE = """mini drama completo, dorama completo dublado, cdrama dublado completo, 
drama chinês dublado, drama coreano dublado, mini drama romance, dorama romance completo,
drama de vingança, romance CEO, drama de reencarnação, isekai romance, 
drama completo português, novela chinesa completa, cdrama 2024 2025,
mini drama épico, drama completo legendado, melhor drama asiático"""


def format_duration(duration_sec: int) -> str:
    h = duration_sec // 3600
    m = (duration_sec % 3600) // 60
    if h > 0:
        return f"{h}h {m:02d}min"
    return f"{m}min"


def build_full_description(
    titulo_seo: str,
    sinopse_reescrita: str,
    hashtags: str,
    generos: str = "Romance, Drama, Ação",
    duration_sec: int = 0,
) -> str:
    """
    Monta a descrição completa respeitando o limite de 3000 chars.
    Zona Humana + Zona de Algoritmo.
    """
    duracao = format_duration(duration_sec)

    description = _DESCRIPTION_TEMPLATE.format(
        titulo_seo=titulo_seo,
        sinopse_reescrita=sinopse_reescrita,
        generos=generos,
        duracao=duracao,
        hashtags=hashtags,
        zona_algoritmo=_ALGORITMO_ZONE,
    )

    # Garante o limite de 3000 chars do Dailymotion
    if len(description) > DM_DESC_LIMIT:
        # Trunca a zona de algoritmo para caber
        overflow = len(description) - DM_DESC_LIMIT
        trimmed_zone = _ALGORITMO_ZONE[:-overflow - 3] + "..."
        description = _DESCRIPTION_TEMPLATE.format(
            titulo_seo=titulo_seo,
            sinopse_reescrita=sinopse_reescrita,
            generos=generos,
            duracao=duracao,
            hashtags=hashtags,
            zona_algoritmo=trimmed_zone,
        )

    return description


# ------------------------------------------------------------------ #
#  Orquestrador: Geração Completa do Pacote SEO
# ------------------------------------------------------------------ #

async def generate_seo_package(candidate: dict) -> dict:
    """
    Recebe um candidato do banco e retorna o pacote SEO completo:
    - title_variants: lista de 3 títulos
    - description: texto formatado final
    - tags: string para campo 'tags' da API
    """
    caption = candidate.get("caption", "")
    sinopse = candidate.get("synopsis", "")
    duration_sec = candidate.get("duration_sec", 0)

    title_base = extract_title_from_caption(caption)
    logger.info("[SEO] Gerando pacote para: '%s'", title_base)

    # 1. Títulos via Autocomplete (sem IA) e Lógica de Dublagem
    title_variants = await generate_title_variants(title_base, caption)
    titulo_principal = title_variants[0] if title_variants else f"🎬 COMPLETO: {title_base}"

    # 2. Sinopse reescrita pelo Gemini
    sinopse_reescrita = await rewrite_synopsis(title_base, sinopse)

    # 3. Tags e Hashtags
    tags_data = await generate_tags(title_base, sinopse_reescrita)

    # 4. Descrição completa
    description = build_full_description(
        titulo_seo=titulo_principal,
        sinopse_reescrita=sinopse_reescrita,
        hashtags=tags_data["hashtags"],
        duration_sec=duration_sec,
    )

    # 5. Persiste variantes no banco
    cand_id = candidate.get("id")
    if cand_id:
        variants = []
        for i, t in enumerate(title_variants):
            variants.append({"candidate_id": cand_id, "variant_type": "title", "content": t, "variant_index": i})
        variants.append({"candidate_id": cand_id, "variant_type": "description", "content": description, "variant_index": 0})
        db.insert_seo_variants(variants)

    result = {
        "title_variants": title_variants,
        "description": description,
        "tags": tags_data["tags"],
        "hashtags": tags_data["hashtags"],
        "char_count": len(description),
    }

    logger.info(
        "[SEO] Pacote gerado: %d variações de título, descrição=%d chars",
        len(title_variants), len(description)
    )
    return result


if __name__ == "__main__":
    import asyncio
    logging.basicConfig(level=logging.INFO)

    async def _test():
        fake_candidate = {
            "id": "test-id",
            "caption": "Renascida Para a Vingança [Parte Única]",
            "synopsis": "Li Wei foi traída pelo marido e pela melhor amiga. Após morrer, ela acorda no passado com todas as memórias do futuro. Desta vez, ela vai se vingar de quem a destruiu.",
            "duration_sec": 5400,
        }
        pkg = await generate_seo_package(fake_candidate)
        print("\n=== TÍTULOS ===")
        for t in pkg["title_variants"]:
            print(f"  {t}")
        print(f"\n=== DESCRIÇÃO ({pkg['char_count']} chars) ===")
        print(pkg["description"][:300] + "...")
        print(f"\n=== TAGS ===\n{pkg['tags']}")

    asyncio.run(_test())
