"""
test_local.py — Validação local de todas as integrações.
Testa cada serviço de forma isolada, sem precisar da VPS.

Rode com: python test_local.py
"""

import asyncio
import os
import sys

# Garante que a raiz do projeto está no path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv(".env")

# ─────────────────────────────────────────
#  Cores para o terminal
# ─────────────────────────────────────────
OK   = "\033[92m✅\033[0m"
FAIL = "\033[91m❌\033[0m"
WARN = "\033[93m⚠️ \033[0m"
INFO = "\033[94mℹ️ \033[0m"

def header(title: str):
    print(f"\n{'─'*50}")
    print(f"  {title}")
    print(f"{'─'*50}")

# ─────────────────────────────────────────
#  TESTE 1 — Supabase
# ─────────────────────────────────────────
async def test_supabase():
    header("TESTE 1: Supabase (Banco de Dados)")
    try:
        from supabase import create_client
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_KEY")

        db = create_client(url, key)

        # Tenta listar tabelas (leitura simples)
        r = db.table("candidates").select("id").limit(1).execute()
        print(f"  {OK}  Conexão estabelecida com sucesso!")
        print(f"  {INFO} URL: {url}")
        print(f"  {INFO} Tabela 'candidates' respondeu: {len(r.data)} registro(s)")

        # Testa inserção com dado fictício
        test_data = {
            "file_unique_id": "TEST_LOCAL_DELETE_ME",
            "msg_id": 99999999,
            "channel_id": 99999999,
            "caption": "[TESTE LOCAL] Drama de Teste Automatizado",
            "duration_sec": 3600,
            "file_size_bytes": 1024,
            "views": 100,
            "reactions": 10,
            "status": "reserve",
        }
        ins = db.table("candidates").insert(test_data).execute()
        inserted_id = ins.data[0]["id"] if ins.data else None
        print(f"  {OK}  INSERT funcionando! ID gerado: {inserted_id}")

        # Testa leitura
        rd = db.table("candidates").select("*").eq("file_unique_id", "TEST_LOCAL_DELETE_ME").execute()
        print(f"  {OK}  SELECT funcionando! Leu {len(rd.data)} registro(s)")

        # Limpa o registro de teste
        db.table("candidates").delete().eq("file_unique_id", "TEST_LOCAL_DELETE_ME").execute()
        print(f"  {OK}  DELETE funcionando! Registro de teste removido.")

        return True

    except Exception as e:
        print(f"  {FAIL} Supabase FALHOU: {e}")
        return False


# ─────────────────────────────────────────
#  TESTE 2 — Dailymotion OAuth
# ─────────────────────────────────────────
async def test_dailymotion():
    header("TESTE 2: Dailymotion (OAuth2 Token)")
    try:
        import httpx

        r = await asyncio.to_thread(
            lambda: __import__("requests").post(
                "https://api.dailymotion.com/oauth/token",
                data={
                    "grant_type": "password",
                    "client_id": os.getenv("DAILYMOTION_CLIENT_ID"),
                    "client_secret": os.getenv("DAILYMOTION_CLIENT_SECRET"),
                    "username": os.getenv("DAILYMOTION_USERNAME"),
                    "password": os.getenv("DAILYMOTION_PASSWORD"),
                    "scope": "manage_videos",
                },
                timeout=15,
            )
        )

        data = r.json()
        if "access_token" in data:
            token = data["access_token"]
            expires = data.get("expires_in", "?")
            print(f"  {OK}  Token OAuth obtido com sucesso!")
            print(f"  {INFO} Token: {token[:20]}...")
            print(f"  {INFO} Expira em: {expires}s")

            # Testa endpoint de informações do usuário
            import requests
            me = requests.get(
                "https://api.dailymotion.com/me",
                headers={"Authorization": f"Bearer {token}"},
                params={"fields": "id,username,videocount"},
                timeout=10,
            ).json()
            print(f"  {OK}  Conta Dailymotion: @{me.get('username')} | {me.get('videocount', '?')} vídeos")
            return True
        else:
            print(f"  {FAIL} Falha no token: {data.get('error_description', data)}")
            return False

    except Exception as e:
        print(f"  {FAIL} Dailymotion FALHOU: {e}")
        return False


# ─────────────────────────────────────────
#  TESTE 3 — Google Gemini
# ─────────────────────────────────────────
async def test_gemini():
    header("TESTE 3: Google Gemini (LLM)")
    try:
        from google import genai
        client = genai.Client(
            api_key=os.getenv("GEMINI_API_KEY"),
            http_options={"api_version": "v1beta"},
        )
        models_to_try = ["gemini-3.1-flash-lite-preview", "gemini-3.1-pro-preview", "gemini-2.5-flash"]
        for model in models_to_try:
            try:
                resp = await asyncio.to_thread(
                    client.models.generate_content,
                    model=model,
                    contents="Diga: Gemini operacional para o DailymotionAgent!",
                )
                text = resp.text.strip()
                print(f"  {OK}  Gemini respondeu com [{model}]!")
                print(f"  {INFO} Resposta: {text[:80]}")
                return True
            except Exception as me:
                print(f"  {WARN} [{model}] falhou: {str(me)[:80]}")
        print(f"  {FAIL} Todos os modelos falharam.")
        return False
    except Exception as e:
        print(f"  {FAIL} Gemini FALHOU: {e}")
        return False


# ─────────────────────────────────────────
#  TESTE 4 — YouTube Autocomplete (SEO)
# ─────────────────────────────────────────
async def test_autocomplete():
    header("TESTE 4: YouTube Autocomplete (SEO Engine)")
    try:
        import httpx, json, re

        titulo = "Renascida Para a Vingança"
        url = "https://suggestqueries.google.com/complete/search"
        params = {"q": titulo, "client": "youtube", "hl": "pt-BR", "gl": "BR"}

        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url, params=params)

        text = r.text
        match = re.search(r"\[.*\]", text, re.DOTALL)
        if match:
            data = json.loads(match.group(0))
            suggestions = data[1] if len(data) > 1 else []
            terms = [s[0] for s in suggestions[:5] if isinstance(s, list)]
            print(f"  {OK}  Autocomplete funcionando!")
            print(f"  {INFO} Título base: '{titulo}'")
            print(f"  {INFO} Sugestões encontradas:")
            for t in terms:
                print(f"       → {t}")
            return True
        else:
            print(f"  {WARN} Autocomplete retornou resposta inesperada.")
            return False

    except Exception as e:
        print(f"  {FAIL} Autocomplete FALHOU: {e}")
        return False


# ─────────────────────────────────────────
#  TESTE 5 — Telethon (Conexão Telegram)
# ─────────────────────────────────────────
async def test_telethon():
    header("TESTE 5: Telethon (MTProto Telegram)")
    print(f"  {INFO} Na PRIMEIRA execução, o Telegram vai pedir o código SMS.")
    print(f"  {INFO} Isso é normal — acontece apenas uma vez.")
    print()

    try:
        from telethon import TelegramClient
        from telethon.errors import SessionPasswordNeededError

        client = TelegramClient(
            os.getenv("TELEGRAM_SESSION_NAME", "dailymotion_agent"),
            int(os.getenv("TELEGRAM_API_ID")),
            os.getenv("TELEGRAM_API_HASH"),
        )

        await client.start()

        me = await client.get_me()
        print(f"  {OK}  Telethon conectado!")
        print(f"  {INFO} Conta: {me.first_name} | @{me.username or 'sem username'} | ID: {me.id}")

        # Testa acesso ao canal de origem
        channel = os.getenv("TELEGRAM_SOURCE_CHANNEL", "@ProducoesIndependentesAsia")
        try:
            entity = await client.get_entity(channel)
            print(f"  {OK}  Canal de origem acessível: {entity.title}")
        except Exception as ce:
            print(f"  {WARN} Canal '{channel}' não acessível: {ce}")

        await client.disconnect()
        return True

    except Exception as e:
        print(f"  {FAIL} Telethon FALHOU: {e}")
        return False


# ─────────────────────────────────────────
#  RUNNER PRINCIPAL
# ─────────────────────────────────────────
async def main():
    print()
    print("╔══════════════════════════════════════════════════╗")
    print("║     DailymotionAgent — Validação Local           ║")
    print("╚══════════════════════════════════════════════════╝")

    results = {}

    results["Supabase"]       = await test_supabase()
    results["Dailymotion"]    = await test_dailymotion()
    results["Gemini"]         = await test_gemini()
    results["Autocomplete"]   = await test_autocomplete()
    results["Telethon"]       = await test_telethon()

    # Resumo final
    header("RESUMO FINAL")
    total = len(results)
    passed = sum(1 for v in results.values() if v)

    for service, ok in results.items():
        icon = OK if ok else FAIL
        print(f"  {icon}  {service}")

    print(f"\n  Resultado: {passed}/{total} serviços operacionais")

    if passed == total:
        print(f"\n  {OK} TUDO PRONTO! O agente está pronto para a VPS.")
    else:
        print(f"\n  {WARN} Corrija os serviços com falha antes de fazer deploy.")


if __name__ == "__main__":
    asyncio.run(main())
