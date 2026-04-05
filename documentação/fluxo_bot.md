1. O Despertar do Dashboard (Health Check e Limites)
   Quando você abre o seu bot privado e digita o comando /start (ou quando o bot te manda um alerta programado), o backend faz uma verificação instantânea de saúde e limites antes de te mostrar qualquer drama.

Consulta de Banco de Dados local: O agente olha a tabela de Postados_Historico das últimas 24 horas.

Cálculo da "Bateria Dailymotion": Ele subtrai o que já foi enviado das suas 10 horas e 15 uploads diários do plano Starter.

Definição de Slots Visíveis: O backend pega os 6 títulos da tabela Top_6_Vitrine. Se você só tem 4 horas de limite restante (o equivalente a uns 2 ou 3 dramas inteiros), o sistema esconde os excedentes na reserva e monta o painel principal apenas com o que é humanamente possível postar naquele dia.

A Interface Inicial (O Menu Principal):
O bot envia uma única mensagem formatada. Ela será o seu ponto central.

🎛️ PAINEL DE CONTROLE - DAILYMOTION
🔋 Capacidade Restante: 04h 15m | 12 Uploads disponíveis.

🎬 SLOT 1: [Hype: 95%] - A Queda de uma Esposa Virgem
⏱️ Duração: 1h 28m | Status: 🔴 Aguardando Validação

🎬 SLOT 2: [Hype: 88%] - Renascida Para a Vingança
⏱️ Duração: 1h 45m | Status: 🔴 Aguardando Validação

(Botões Inline fixados embaixo da mensagem):
[ ⚙️ Validar Slot 1 ] | [ ⚙️ Validar Slot 2 ]

2. O Túnel de Validação (O Carrossel Inteligente)
   Ao clicar em [ ⚙️ Validar Slot 1 ], a mágica da API do Telegram (edit_message_media e edit_message_text) entra em ação. O painel principal some e a mesma mensagem se transforma na sua estação de trabalho, passo a passo.

Passo A: A Escolha do Título SEO
O backend traz as opções geradas pela IA na fase anterior. A tela muda para:

🏷️ PASSO 1/4: Escolha o Título (Slot 1)

Opção Atual: > 🎬 COMPLETO: A Queda de uma Esposa Virgem (His Contracted Virgin) - Mini Drama Dublado

(Botões Inline):
[ ◀️ Anterior ] | [ ✅ Confirmar Título ] | [ Próxima ▶️ ]

Mecânica: Clicar nas setas faz o backend trocar apenas o texto da "Opção Atual" instantaneamente, puxando do banco de dados as variações criadas pela IA.

Passo B: A Revisão da Sinopse e Tags
Após confirmar o título, a tela pisca e muda para o Passo 2.

📝 PASSO 2/4: Revisão da Descrição

Texto Atual:
[Aqui aparece o template completo com a sinopse reescrita pela IA, Gêneros e as #Hashtags prontas para o algoritmo do Dailymotion].

(Botões Inline):
[ ◀️ Anterior ] | [ ✅ Confirmar Descrição ] | [ Próxima ▶️ ]

Mecânica: Você avalia se a IA não alucinou nenhum termo. Se não gostou, gira para a próxima versão de texto.

Passo C: A Escolha da Capa (Modo Mídia)
Aqui a mensagem transiciona de texto para uma mensagem com imagem anexada (Media Message).

🖼️ PASSO 3/4: Escolha a Capa Limpa

(A imagem roubada do canal concorrente aparece grande na tela)
Fonte: Canal AcervoCurtas

(Botões Inline):
[ ◀️ Capa Anterior ] | [ ✅ Confirmar Capa ] | [ Próxima Capa ▶️ ]

Mecânica: Como o agente raspou 3 capas limpas dos canais clones (como definimos na fase de hype global), você navega pelas imagens. Ao clicar em confirmar, o backend salva a URL dessa imagem para ser enviada via API ao Dailymotion depois.

Passo D: O Match do Vídeo (Prova de Vida)
O último e mais importante passo. O vídeo pesado de 2GB não pode ser assistido no Telegram facilmente, então o agente faz um truque.

🎥 PASSO 4/4: Confirmação do Arquivo de Vídeo

(A imagem muda para um frame aleatório, como uma thumbnail ou um gif de 3 segundos extraído do primeiro minuto do vídeo de 40+ min).

O vídeo associado a esta sinopse bate com a imagem acima?

(Botões Inline):
[ ❌ Erro de Match (Descartar) ] | [ ✅ TUDO CERTO! ]

Mecânica: Se o frame mostrar os mesmos atores da capa, o Match Reverso funcionou perfeitamente.

3. O Retorno ao Lobby e o Gatilho Final
   Ao clicar em [ ✅ TUDO CERTO! ], o túnel se fecha. A mensagem no chat volta a ser exatamente aquele Menu Principal (Lobby) do início, mas com uma diferença crucial: o estado do banco de dados mudou.

🎛️ PAINEL DE CONTROLE - DAILYMOTION

🎬 SLOT 1: [Hype: 95%] - A Queda de uma Esposa Virgem
⏱️ Duração: 1h 28m | Status: 🟢 PRONTO PARA ENVIO

🎬 SLOT 2: [Hype: 88%] - Renascida Para a Vingança
⏱️ Duração: 1h 45m | Status: 🔴 Aguardando Validação

(Botões Inline atualizados):
[ 🚀 ENVIAR SLOT 1 ] | [ ✏️ Re-editar Slot 1 ] | [ ⚙️ Validar Slot 2 ]

4. A Dinâmica da Reserva (O Plano B)
   O que acontece se, no Passo D (Match do Vídeo), você perceber que o canal original postou o vídeo errado e clicar em [ ❌ Descartar ]?
   O backend deleta esse Slot 1. Imediatamente, ele acessa os 2 títulos que estavam "invisíveis" na reserva da Top_6_Vitrine e puxa o primeiro da fila. O seu Menu Principal é atualizado automaticamente preenchendo o vazio com um novo drama para ser validado.

A beleza dessa estrutura é que você pode fazer tudo isso no ônibus, na fila do banco ou no sofá, usando apenas o polegar. Toda a manipulação de dados complexos fica isolada no seu servidor.
