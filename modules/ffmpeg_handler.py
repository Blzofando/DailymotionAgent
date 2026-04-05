"""
modules/ffmpeg_handler.py — Inspeção e corte automático de vídeos via FFmpeg.

Fase 3 do pipeline de upload:
  1. ffprobe → lê duração e tamanho do arquivo local
  2. Se dentro dos limites → pass-through (Caminho A)
  3. Se exceder → corta em exatos 1h59m50s (Parte 1) e enfileira Parte 2 (Caminho B)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from core.config import config
from core import database as db

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------ #
#  Estrutura de resultado
# ------------------------------------------------------------------ #

@dataclass
class InspectionResult:
    duration_sec: float
    file_size_bytes: int
    needs_split: bool
    part1_path: Optional[str] = None
    part2_path: Optional[str] = None
    part1_duration_sec: Optional[float] = None
    part2_duration_sec: Optional[float] = None


# ------------------------------------------------------------------ #
#  ffprobe — leitura de metadados
# ------------------------------------------------------------------ #

async def probe_file(filepath: str) -> dict:
    """
    Executa ffprobe e retorna os metadados do arquivo como dict.
    Lança FileNotFoundError se o arquivo não existir.
    """
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"Arquivo não encontrado: {filepath}")

    cmd = [
        config.agent.ffprobe_path,
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        filepath,
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        raise RuntimeError(f"ffprobe falhou: {stderr.decode()}")

    return json.loads(stdout.decode())


# ------------------------------------------------------------------ #
#  Inspeção principal
# ------------------------------------------------------------------ #

async def inspect_video(filepath: str) -> InspectionResult:
    """
    Inspeciona o vídeo e decide se precisa de corte.
    Retorna InspectionResult com todos os metadados necessários.
    """
    logger.info("[FFMPEG] Inspecionando: %s", filepath)

    probe_data = await probe_file(filepath)
    format_info = probe_data.get("format", {})

    duration_sec = float(format_info.get("duration", 0))
    file_size_bytes = int(format_info.get("size", os.path.getsize(filepath)))

    max_dur = config.agent.max_duration_sec
    max_size = config.agent.max_size_bytes

    needs_split = duration_sec > max_dur or file_size_bytes > max_size

    logger.info(
        "[FFMPEG] Duração: %ds | Tamanho: %.2fGB | Precisa corte: %s",
        int(duration_sec),
        file_size_bytes / (1024 ** 3),
        needs_split,
    )

    return InspectionResult(
        duration_sec=duration_sec,
        file_size_bytes=file_size_bytes,
        needs_split=needs_split,
    )


# ------------------------------------------------------------------ #
#  Corte FFmpeg (Caminho B)
# ------------------------------------------------------------------ #

# Ponto de corte: 1h59m50s em segundos
CUT_POINT_SEC = 7190  # = 1*3600 + 59*60 + 50


async def split_video(
    filepath: str,
    output_dir: Optional[str] = None,
    candidate_id: Optional[str] = None,
) -> InspectionResult:
    """
    Corta o vídeo em Parte 1 (0 → CUT_POINT_SEC) e Parte 2 (restante).
    Usa -c copy para evitar re-encoding (ultrarrápido, sem perda de qualidade).
    """
    path = Path(filepath)
    out_dir = Path(output_dir) if output_dir else path.parent
    stem = path.stem

    part1_path = str(out_dir / f"{stem}_parte1{path.suffix}")
    part2_path = str(out_dir / f"{stem}_parte2{path.suffix}")

    logger.info("[FFMPEG] Iniciando corte: '%s'", filepath)

    # Corta Parte 1
    await _run_ffmpeg_cut(
        src=filepath,
        dst=part1_path,
        start="00:00:00",
        duration=CUT_POINT_SEC,
    )

    # Corta Parte 2 (do ponto de corte até o fim)
    await _run_ffmpeg_cut(
        src=filepath,
        dst=part2_path,
        start_sec=CUT_POINT_SEC,
    )

    # Remove arquivo original para liberar disco
    os.remove(filepath)
    logger.info("[FFMPEG] Arquivo original removido: %s", filepath)

    # Coleta metadados das partes
    probe1 = await probe_file(part1_path)
    probe2 = await probe_file(part2_path)
    dur1 = float(probe1["format"].get("duration", CUT_POINT_SEC))
    dur2 = float(probe2["format"].get("duration", 0))
    size2 = int(probe2["format"].get("size", 0))

    logger.info("[FFMPEG] Parte 1: %ds | Parte 2: %ds", int(dur1), int(dur2))

    # Persiste Parte 2 na fila do banco (se candidato informado)
    if candidate_id:
        db.add_pending_part({
            "original_candidate_id": candidate_id,
            "part_number": 2,
            "title_suffix": "[Parte 2]",
            "msg_id": 0,       # Será atualizado pelo caller
            "channel_id": 0,   # Será atualizado pelo caller
            "file_unique_id": f"{candidate_id}_part2",  # ID sintético
            "status": "queued",
        })
        logger.info("[FFMPEG] Parte 2 enfileirada no banco para processamento futuro.")

    return InspectionResult(
        duration_sec=float(probe1["format"].get("duration", CUT_POINT_SEC)),
        file_size_bytes=int(probe1["format"].get("size", 0)),
        needs_split=True,
        part1_path=part1_path,
        part2_path=part2_path,
        part1_duration_sec=dur1,
        part2_duration_sec=dur2,
    )


async def _run_ffmpeg_cut(
    src: str,
    dst: str,
    start: Optional[str] = None,
    start_sec: Optional[int] = None,
    duration: Optional[int] = None,
) -> None:
    """Executa o corte FFmpeg de forma assíncrona."""
    cmd = [config.agent.ffmpeg_path, "-y"]

    if start_sec is not None:
        cmd += ["-ss", str(start_sec)]
    elif start:
        cmd += ["-ss", start]

    cmd += ["-i", src]

    if duration is not None:
        cmd += ["-t", str(duration)]

    # Cópia direta sem re-encode — ultrarrápido
    cmd += ["-c", "copy", dst]

    logger.debug("[FFMPEG] CMD: %s", " ".join(cmd))

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg falhou no corte:\n{stderr.decode()[-500:]}")

    logger.info("[FFMPEG] Corte concluído → %s", dst)


# ------------------------------------------------------------------ #
#  Extração de Frame para Preview (Dashboard)
# ------------------------------------------------------------------ #

async def extract_preview_frame(filepath: str, output_path: str, timestamp: str = "00:01:00") -> str:
    """
    Extrai um frame do vídeo para exibição no passo 4 do túnel de validação.
    Retorna o caminho da imagem gerada.
    """
    cmd = [
        config.agent.ffmpeg_path,
        "-y",
        "-ss", timestamp,
        "-i", filepath,
        "-frames:v", "1",
        "-q:v", "2",
        output_path,
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await proc.communicate()

    if os.path.exists(output_path):
        logger.info("[FFMPEG] Frame extraído: %s", output_path)
        return output_path
    else:
        raise RuntimeError(f"Falha ao extrair frame de: {filepath}")
