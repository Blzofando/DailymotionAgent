---
trigger: model_decision
description: Protocolo de entrega pós-implementação para garantir a continuidade do projeto.
---

Sempre que você finalizar uma implementação ou alteração no código, realize uma varredura em busca de dependências que dependam de ação humana. Gere um relatório imediato contendo:

Pendências de Configuração: Identifique Variáveis de Ambiente (API Keys, Tokens, IDs) ou constantes que precisam de valores reais.

Instruções de Obtenção: Explique exatamente onde eu encontro essa info (ex: Console do Google, Painel do Supabase, BotFather) e o passo a passo para gerar o dado.

Local de Inserção: Indique o caminho do arquivo (ex: .env, config.py) e o formato exato que o dado deve ter.

Ações Externas: Se for necessário criar um Bucket, uma Tabela ou uma Webhook manualmente, detalhe os cliques necessários na interface da plataforma.

Não considere a tarefa concluída até que este relatório de pendências tenha sido entregue com clareza.
