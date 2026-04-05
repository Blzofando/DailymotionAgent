"""
main.py — Orquestrador Principal do DailymotionAgent.

Responsabilidades:
  - Inicializa o cliente Telethon (MTProto)
  - Inicia o Bot de Controle Telegram (Dashboard)
  - Agenda o ciclo diário de mineração (validator.run_full_mining_cycle)
  - Mantém tudo rodando 24/7 de forma assíncrona
"""

import asyncio
import logging
import sys
from datetime import datetime

from telegram.ext import Application

from core.config import config
from bot.bot_controller import create_bot
from modules.validator import run_full_mining_cycle

# Configuração de logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("agent.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("main")

# Suprime logs verbosos de bibliotecas externas
logging.getLogger("telethon").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)


# ------------------------------------------------------------------ #
#  Ciclo Agendado de Mineração
# ------------------------------------------------------------------ #

MINING_HOUR = 6  # Hora para rodar a mineração (6h da manhã no servidor)


async def scheduled_mining_loop():
    """
    Loop que aguarda o horário configurado e dispara o ciclo de mineração.
    Roda uma vez por dia automaticamente.
    """
    while True:
        now = datetime.now()
        next_run = now.replace(hour=MINING_HOUR, minute=0, second=0, microsecond=0)

        if now >= next_run:
            next_run = next_run.replace(day=next_run.day + 1)

        wait_seconds = (next_run - now).total_seconds()
        logger.info("[SCHEDULER] Próximo ciclo de mineração em %.0f minutos.", wait_seconds / 60)
        await asyncio.sleep(wait_seconds)

        try:
            logger.info("[SCHEDULER] Disparando ciclo de mineração agendado.")
            await run_full_mining_cycle()
        except Exception as e:
            logger.error("[SCHEDULER] Erro no ciclo de mineração: %s", e, exc_info=True)


# ------------------------------------------------------------------ #
#  Ponto de Entrada Assíncrono
# ------------------------------------------------------------------ #

async def main():
    logger.info("=" * 60)
    logger.info(" DailymotionAgent iniciando...")
    logger.info("=" * 60)

    # Importa Telethon aqui para evitar import circular
    from telethon import TelegramClient

    telethon = TelegramClient(
        config.telegram.session_name,
        config.telegram.api_id,
        config.telegram.api_hash,
    )

    # Conecta o Telethon (autentica na primeira execução)
    await telethon.start()
    logger.info("[MAIN] Telethon conectado como usuário MTProto.")

    # Cria o Bot Telegram
    bot_app: Application = create_bot(telethon)

    # Inicializa o bot sem polling bloqueante
    await bot_app.initialize()
    await bot_app.start()
    await bot_app.updater.start_polling(drop_pending_updates=True)
    logger.info("[MAIN] Bot de controle iniciado. Aguardando comandos no Telegram.")

    # Inicia o agendador de mineração em background
    mining_task = asyncio.create_task(scheduled_mining_loop())

    # Opcional: roda o ciclo uma vez imediatamente ao iniciar
    logger.info("[MAIN] Rodando ciclo de mineração inicial...")
    try:
        await run_full_mining_cycle()
    except Exception as e:
        logger.error("[MAIN] Erro no ciclo inicial: %s", e, exc_info=True)

    logger.info("[MAIN] Sistema operacional. Pressione Ctrl+C para encerrar.")

    try:
        # Mantém rodando indefinidamente
        await asyncio.Event().wait()
    except (KeyboardInterrupt, SystemExit):
        logger.info("[MAIN] Encerrando graciosamente...")

    # Cleanup
    mining_task.cancel()
    await bot_app.updater.stop()
    await bot_app.stop()
    await bot_app.shutdown()
    await telethon.disconnect()
    logger.info("[MAIN] Agente encerrado com sucesso.")


if __name__ == "__main__":
    asyncio.run(main())
