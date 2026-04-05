FASE 1: O Gatilho e Preparação (Lock do Sistema)
Quando o dedo bate no [ 🚀 ENVIAR SLOT 1 ], o backend precisa travar a requisição para não gerar envios duplicados se você clicar duas vezes sem querer.

Alteração de Estado Visual: Imediatamente, o painel muda o botão para [ ⏳ Baixando do Telegram... 0% ]. Isso tranquiliza você de que o comando foi recebido.

Lock no Banco de Dados: O sistema marca o Slot 1 como Em Processamento. Isso impede que outras instâncias do bot tentem acessar esse mesmo arquivo.

Resgate de Variáveis: O agente busca no banco: o ID da mensagem do vídeo pesado, o Título SEO, a Sinopse Master, as Tags, e a URL da Capa Limpa que você aprovou.

FASE 2: A Extração MTProto (Telegram ➡️ VPS)
A API de Bots padrão não aguenta 2 GB. Aqui a biblioteca Telethon (ou Pyrogram) atua como um usuário real fazendo o download.

Download em Blocos (Chunking Assíncrono):

O seu script em Python não pode tentar jogar 2 GB na memória RAM da VPS de uma vez, senão o servidor trava.

Ele usa o método assíncrono (ex: client.iter_download()) para baixar o vídeo em pequenos pedaços (blocos de 1 MB) e escrever direto no disco (HD/SSD) da sua máquina.

O Feedback em Tempo Real:

A cada 10% de progresso, o script atualiza o botão no seu painel: [ ⏳ Baixando... 10% ], [ ⏳ Baixando... 20% ].

Verificação de Integridade:

Terminou o download? O script confere se o tamanho do arquivo no disco da VPS bate exatamente com o tamanho reportado pelo Telegram. Se houver corrupção, ele apaga e tenta de novo automaticamente.

FASE 3: O Cérebro de Divisão (O Inspetor FFmpeg)
O arquivo está seguro na VPS. Antes de mandar para a rua, o agente confere as regras do jogo.

A Prova Real de Limites: O Python aciona uma biblioteca como o ffprobe (ferramenta do FFmpeg) para ler os metadados do arquivo local. Ele pergunta: "Esse arquivo tem menos de 4 GB e menos de 2 horas?"

Caminho A (Passe Livre): Se a resposta for sim (a maioria dos seus mini-dramas), ele avança direto para a Fase 4.

Caminho B (O Corte de Segurança): Se o vídeo tiver 2h15m, o agente entra no modo de emergência.

Ele aciona o FFmpeg silenciosamente para cortar o vídeo em exatas 1h59m50s (Parte 1).

O restante do arquivo vira a Parte 2.

O agente atualiza o título em tempo real adicionando [Parte 1], guarda a Parte 2 no banco de dados e segue o fluxo usando apenas a Parte 1.

FASE 4: O Upload Server-to-Server (VPS ➡️ Dailymotion)
Esta é a fase mais crítica. O fluxo oficial da API do Dailymotion exige três etapas precisas.

A Requisição de URL (Handshake):

O script faz uma chamada leve para a API do Dailymotion autenticada com seu token de criador pedindo permissão: "Quero enviar um arquivo".

O Dailymotion responde com uma URL temporária e exclusiva de upload.

O Envio Streamado (Multipart Upload):

O painel no seu Telegram atualiza para: [ 🚀 Enviando p/ Dailymotion... ].

O script Python pega o arquivo no disco da VPS e começa a enviar para a URL recebida usando a biblioteca requests ou httpx no modo stream. Novamente, isso garante que a RAM do seu servidor não estoure, enviando direto do disco para a rede.

A Publicação e os Metadados:

Quando o vídeo termina de subir, o Dailymotion devolve um Video_ID.

O seu agente pega esse ID e faz uma última requisição POST violenta, publicando o vídeo e injetando de uma vez só:

O Título SEO.

A Descrição formatada e as Hashtags.

A URL da Capa Limpa (o servidor do Dailymotion vai baixar essa imagem instantaneamente).

O Gatilho da Capa na Fase 4
O Upload do Vídeo (A Parte Pesada): A sua VPS termina de enviar o arquivo de vídeo bruto (os 2 a 4 GB) para os servidores do Dailymotion via API.

O Retorno do ID: Assim que a transferência é concluída, a API devolve para o seu código em Python o ID único gerado para aquele vídeo (ex: x84sh87).

A Injeção Rápida (O Truque da URL):

O agente não inicia um novo processo de upload para enviar a foto da capa do seu disco.

Ele faz uma requisição POST instantânea (no endpoint de edição do vídeo) para "vestir" o arquivo que acabou de subir.

É nesse exato momento que ele injeta o Título SEO, a Sinopse e usa o parâmetro thumbnail_url.

O seu script simplesmente manda em texto a URL pública da capa limpa que você escolheu no Dashboard (aquela que o agente raspou dos canais concorrentes durante a Busca Global).

O Dailymotion Trabalha por Você: O próprio servidor deles acessa o link e baixa a imagem nativamente. Isso leva milissegundos e zera o consumo de banda de upload da sua VPS nessa etapa.

Resumindo a mecânica para o seu Dashboard:
Quando você navegava pelas imagens e clicava em [ ✅ Confirmar Capa ] lá no túnel de validação do Telegram, o agente não baixou a foto. Ele apenas salvou o endereço de texto (URL) dessa foto no banco de dados. Essa URL ficou guardada esperando a transferência do vídeo acabar para ser injetada no final.

Essa injeção direta via URL resolve o seu problema de velocidade e garante que o seu painel de controle nunca fique travado carregando imagens pesadas na hora do clique final.

FASE 5: A Faxina e a Comemoração (Clean & Report)
O seu agente foi programado para não deixar rastros e manter a sua infraestrutura limpa.

Destruição Local: O script executa um comando rígido (os.remove()) para apagar o vídeo de 2 a 4 GB do disco da VPS. Se ele não fizer isso, em três dias o seu servidor lota e o projeto inteiro cai.

Registro Histórico: O agente move os dados do Top_6_Vitrine para a tabela de Postados_Historico, garantindo que esse vídeo não seja garimpado de novo nos próximos meses.

O Relatório Final: O seu bot no Telegram pisca com uma notificação limpa, fechando o ciclo.

✅ UPLOAD CONCLUÍDO COM SUCESSO!
🎬 Título: Sua Virgem Por Contrato (Dublado)
🔗 Link: https://dailymotion.com/video/x...

🔋 Capacidade Atualizada: 02h 45m restantes hoje.
O Painel de Controle foi atualizado.

Esse fluxo garante que o peso da operação fique restrito à comunicação entre grandes datacenters (Servidores do Telegram -> Sua VPS -> Servidores do Dailymotion), sem gargalos.
