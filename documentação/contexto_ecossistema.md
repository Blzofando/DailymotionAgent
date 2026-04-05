📡 O Ecossistema de Trabalho: Canal de Origem e Mídia

1. O Alvo de Mineração:
   Trabalharemos em canais de "Produções Independentes" e catálogos de dramas asiáticos (como o Produções Independentes Ásia). Esses canais são agregadores: eles não produzem, eles republicam conteúdos que estão viralizando no TikTok e em plataformas chinesas.

2. A Anatomia do "Combo de Postagem":
   O agente deve entender que a postagem não é unitária. Ela é um Combo Fragmentado, composto geralmente por 2 a 3 mensagens seguidas:

Mensagem A (O Pôster/Sinopse): Uma imagem vertical poluída com marcas d'água, contendo um texto longo com: Título em PT, Título em EN, Título Original (CN/KR), Gêneros, Duração e uma Sinopse dramática.

Mensagem B (O Vídeo Âncora): Enviada logo após a sinopse. É um arquivo pesado (2GB a 4GB), formato vertical (9:16), com duração longa (geralmente entre 1h e 2h), contendo o drama completo ou uma compilação de episódios.

Mensagem C (O Link VIP/Anúncio): Muitas vezes o canal posta um link de "Canal Privado" ou botão de "Entrar no Grupo" logo abaixo do vídeo. O agente deve ter inteligência para ignorar essa terceira mensagem.

3. O Desafio dos Títulos Rotativos:
   Diferente de filmes de cinema, esses dramas mudam de nome para "testar" o que atrai mais cliques no TikTok.

O robô deve saber que o título na Legenda do Vídeo (ex: "Sua Virgem por Contrato") pode ser ligeiramente diferente do título no Pôster (ex: "Dominação por Contrato").

O agente usará o Match Reverso (Fuzzy Matching) para entender que, apesar da diferença de pontuação ou palavras sinônimas, tratam-se da mesma obra.

🤖 Comportamento do Agente no Contexto de Legendas
Como 80% dos vídeos possuem o título escrito na legenda do arquivo, o agente usará essa legenda como a Âncora de Verdade.

Ele lê o vídeo.

Extrai o título da legenda.

Busca a sinopse "subindo" o histórico.

Se houver conflito de nomes, o agente prioriza o nome que tiver maior volume de buscas no Autocomplete, garantindo que o título final no Dailymotion seja o que as pessoas realmente estão digitando.

📊 O Dashboard de Gestão (A Sua Central)
O contexto da sua interação com o robô será de Alta produtividade / Baixo esforço:

O robô apresenta os dramas já limpos de emojis, anos e poluição visual.

O sistema de Slots no Dashboard respeita a hierarquia do canal: ele sempre tentará te mostrar o que acabou de sair (os 10 frescos) misturado com o que está "moendo" de visualizações (os 20 de hype).

Contexto de Upload: O robô sabe que você é um Soldado e Estudante de Administração, ou seja, seu tempo é curto. Por isso, o fluxo é desenhado para que uma aprovação de 6 vídeos não tome mais que 5 minutos do seu dia.

🗄️ Resumo do Banco de Dados (Supabase)
O Supabase atuará como a "caixa preta" do avião.

Não salva vídeos.

Salva a "Digital" do vídeo: Ele guarda o file_unique_id do Telegram. Mesmo que o admin do canal mude o nome do arquivo ou apague e poste de novo, o Supabase reconhece que aquele conteúdo já passou pela sua mão e impede a duplicata.

Estado de Pendência: Ele gerencia os cortes. Se um drama de 3 horas for fatiado, o Supabase garante que a "Parte 2" não se perca e apareça no seu painel no dia seguinte como prioridade.
