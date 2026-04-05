📑 Resumo Geral: Agente Autônomo de Curadoria (C-Dramas)

1. Contexto e Objetivo
   O projeto consiste em um ecossistema automatizado para minerar, otimizar e postar mini-dramas verticais (C-Dramas/J-Dramas) em um canal do Dailymotion. O objetivo é escalar a criação de conteúdo "faceless", utilizando inteligência de dados para identificar tendências antes da concorrência e garantir um SEO impecável que domine as buscas orgânicas.

2. Arquitetura Técnica
   Cérebro (Backend): Script Python rodando em uma VPS (Oracle/Azure) 24/7.

Interface (Frontend): Um Bot de Controle privado no Telegram que funciona como um Dashboard administrativo.

Banco de Dados: Supabase (PostgreSQL) para gerenciar estados, histórico de postagens (anti-duplicação) e filas de pendências.

Processamento de Mídia: FFmpeg para análise técnica, extração de frames e cortes automáticos de duração.

Inteligência: APIs de LLM (Gemini/OpenAI) para reescrita de sinopses e estruturação de dados, e APIs de Autocomplete para SEO real.

3. A Lógica do Funil (O Diferencial)
   O sistema não trabalha com "achismos". Ele opera um funil de conversão de dados:

Garimpo Bruto: Varre 100 vídeos longos (>40min) de canais de origem.

Filtro de Tração: Seleciona os 10 mais recentes e os 20 com maior taxa de reação (hype nativo).

Casamento de Dados: Localiza a sinopse correspondente via "busca reversa" no histórico do Telegram.

Validação Global: Cruza o título com a quantidade de "canais clones" no Telegram para confirmar o viral.

4. O Diferencial Competitivo (SEO de Elite)
   Títulos Blindados: Títulos montados com base em sugestões reais de busca, sem "alucinação" da IA, preservando o nome original da obra.

Descrições Massivas: Aproveitamento total dos 3000 caracteres do Dailymotion, preenchendo o excesso com "Zonas de Algoritmo" (nuvens de tags e hashtags de cauda longa).

Capas Limpas: O robô infiltra-se em canais concorrentes para "roubar" o pôster oficial sem marcas d'água, garantindo um visual profissional.

5. Gestão de Limites e Sustentabilidade
   Cota Dailymotion: O bot monitora em tempo real a sua "bateria" de 10 horas diárias e 15 uploads, sugerindo postagens ou fatiando vídeos em Parte 1 e 2 automaticamente.

Infraestrutura Leve: O sistema usa transferência Server-to-Server. O vídeo nunca passa pelo seu computador pessoal ou celular, e a VPS mantém-se limpa deletando cada arquivo após o upload concluído.

O resultado final: Você terá uma máquina de postagem onde o seu único trabalho é abrir o Telegram uma vez por dia, navegar por um "carrossel" de 6 dramas já mastigados pelo robô, conferir se a capa e o título estão bonitos e apertar [🚀 POSTAR ].
