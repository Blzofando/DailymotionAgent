FASE 1: O Rastreador de Vídeos (Os 100 Âncoras)
O agente ignora completamente textos, fotos e conversas. Ele agora caça apenas o "Ouro".

A Varredura de Mídia: O script varre o histórico do Telegram de baixo para cima (do mais recente para o mais antigo) filtrando exclusivamente mensagens que contenham um anexo do tipo Vídeo.

O Filtro de Ouro: Ele verifica a duração do arquivo. Menos de 40 minutos? Ignora. Tem 40 minutos ou mais? Ele captura.

A Coleta de Dados Brutos: Para cada vídeo aprovado, ele salva na memória: o ID da mensagem, as Visualizações, o total de Reações e o texto da legenda (caption).

O Alvo: Ele repete isso até acumular as 100 mensagens de vídeos longos mais recentes do canal.

FASE 2: A Peneira de Vídeos (O Corte para 30)
Com os 100 vídeos longos garantidos, o agente aplica a matemática do engajamento para não perder tempo processando texto inútil.

Os 10 Fresquinhos: Ele separa imediatamente os 10 vídeos mais recentes dessa lista de 100, garantindo que o seu canal seja o primeiro a surfar nos lançamentos.

Os 20 Titãs (Hype Nativo): Dos 90 vídeos restantes, ele calcula a taxa direta: Reações do Vídeo / Visualizações do Vídeo. Ele pega os 20 com maior engajamento.

A Lista Focada: Temos agora 30 vídeos de altíssimo potencial. O restante é deletado da memória temporária.

FASE 3: O Casamento Reverso (A Busca pela Sinopse)
É aqui que a sua ideia de aceitar variações brilha. O agente tem os 30 vídeos, mas precisa da sinopse para criar uma descrição decente e postar.

Extração do Título Base: O agente lê a legenda do vídeo. Geralmente, a legenda tem algo como "Sua Virgem por Contrato [Parte Única]". O agente passa isso por uma limpeza rápida para extrair apenas o núcleo do nome.

A Lógica do Ponteiro Reverso: Para o vídeo #1 (ex: ID 5003), o agente começa a olhar para as mensagens anteriores (ID 5002, 5001, 5000...).

Fuzzy Matching (Comparação Flexível): O agente usa um algoritmo de similaridade de strings (como a distância de Levenshtein). Ele compara o título que achou na legenda com o texto das mensagens de cima.

A Mágica: Se a legenda diz "Renascida, para a Vingança" e o post de cima diz "🎥 Renascida para a vingança (2025)", o script detecta uma correspondência de 85% a 90% (ignorando a vírgula, a caixa alta, o emoji e o ano).

Bateu a porcentagem de semelhança? Ele decreta: Combo Validado. Temos o Vídeo + a Sinopse Original.

FASE 4: O Hype Avançado e Prova Social
Com os 30 Combos (Vídeo + Sinopse) perfeitamente casados, o agente vai validar se a febre é real no Telegram afora.

A Lavanderia: O texto da sinopse passa pela IA para limpar a sujeira visual e estruturar os títulos originais (Inglês/Mandarim).

Teste dos Clones (Busca Global): O agente pega o título limpo e pesquisa na rede do Telegram. Quantos canais estão promovendo esse drama hoje?

A Nota Final: O Hype definitivo é selado combinando a força do vídeo original com a quantidade de "concorrência" encontrada. Os 6 melhores formam o Top 6 Vitrine.

FASE 5: O Dashboard do Diretor
Essa etapa permanece intacta e blindada.
O agente consulta o seu saldo na API do Dailymotion, calcula os limites de horas e exibe o painel limpo com as setinhas para você validar Capa, Sinopse e o Match do Vídeo, liberando o botão de postar apenas no final.

Essa mudança de rastrear o vídeo primeiro deixou a arquitetura muito mais econômica e inteligente, Alessandro. Considerando que na Fase 3 o agente vai olhar para as mensagens anteriores buscando a sinopse, qual seria o limite seguro de mensagens que ele deve "subir" para tentar achar o texto antes de desistir e assumir que o vídeo foi postado sem sinopse? (Ex: ler até 5 mensagens acima, 10 mensagens acima?)
