# Contexto para adaptar monitores locais de preços

Este arquivo registra decisões e aprendizados do monitor Kindle para servir de ponto de partida em futuros projetos locais no Windows. Ele descreve a implementação atual; não significa que um novo produto funcionará sem adaptação das consultas e dos seletores.

## Arquitetura atual

- **Python:** script único `kindle.py`; as opções específicas do produto ficam nas constantes no início do arquivo.
- **Navegação:** Selenium controla o Chrome em modo headless. As funções `buscar_*` visitam as fontes e extraem dados com seletores CSS/XPath.
- **Fontes deste projeto:** Amazon Brasil, Kalunga, Pelando, Zoom e Buscapé.
- **Persistência:** `sqlite3` grava alterações em `historico_kindle.db`, ao lado do script.
- **Notificações:** `winotify` apresenta um alerta nativo do Windows quando o preço atende ao limite e é novo ou menor que o último preço salvo.
- **Agendamento:** `rodar_kindle.bat` pode ser chamado pelo Agendador de Tarefas. Ele usa a pasta do próprio arquivo e requer `python` no `PATH`.
- **Logs:** o `.bat` redireciona a saída para `execucoes.log`; o script limita o crescimento do log em execuções subsequentes.

## Fluxo de uma execução

1. `executar_varredura` prepara o log e abre o banco/tabela.
2. `configurar_driver` inicia o Chrome em modo headless.
3. Cada função `buscar_*` acessa uma fonte, extrai título/preço/link e aplica `produto_valido`.
4. Os links são normalizados e os resultados repetidos da mesma fonte/título são reduzidos ao menor preço daquela rodada.
5. O último preço salvo é comparado com o resultado atual. Somente resultados novos ou com preço diferente são inseridos.
6. Uma notificação é enviada quando o preço está no máximo em `PRECO_ALVO_ALERTA` e é uma oferta nova ou uma queda.
7. O navegador e a conexão SQLite são encerrados no bloco `finally`.

## Adaptar para outro produto

Manter o projeto funcionando para um produto diferente exige mais do que trocar o nome no título. Antes de executar:

1. Defina um nome de arquivo/banco apropriado e atualize os textos da notificação.
2. Ajuste `PRECO_MINIMO_REAL`, `PRECO_ALVO_ALERTA` e `PALAVRAS_BANIDAS`.
3. Adapte o termo obrigatório e as regras em `produto_valido`.
4. Atualize as URLs de busca, seletores e extração de título/preço/link nas funções `buscar_*`.
5. Revise se os filtros específicos, como status encerrado, se aplicam às novas páginas.
6. Faça uma execução manual, compare os resultados com as páginas e inspecione o banco antes de configurar o agendamento.

Cada site pode alterar seus layouts e regras de acesso. Prefira integrações ou APIs oficiais quando disponíveis, respeite os termos e limites de cada site e não tente contornar controles de acesso. Quando uma fonte falhar, investigue a alteração de página ou remova/substitua a fonte em vez de assumir que o seletor antigo continua válido.

## Cuidados operacionais

- O caminho do banco é calculado a partir da localização do script para que o Agendador não crie outro banco em diretório de trabalho diferente.
- O `.gitignore` exclui `historico_kindle.db`, arquivos auxiliares SQLite e logs. Esses itens são dados de execução locais e não devem ser publicados por padrão.
- `requirements.txt` contém apenas pacotes de terceiros. Módulos como `sqlite3`, `os`, `re`, `time`, `datetime` e `urllib.parse` fazem parte do Python.
- `rodar_kindle.bat` usa `python` no `PATH`; valide o comando no mesmo perfil de usuário configurado na tarefa agendada.
- A notificação do Windows pode depender de uma sessão de usuário iniciada e das configurações de notificações do sistema.
- Verifique os seletores periodicamente: um site pode mudar a estrutura sem aviso e passar a retornar zero resultados.

## Prompt-base para uma nova implementação

```text
Crie um monitor local de preços para [PRODUTO] em Python para Windows.

Requisitos:
- Busca em [FONTES], usando APIs oficiais quando disponíveis ou automação compatível com os termos de cada site.
- Configuração explícita do termo de busca, preço mínimo, preço-alvo e palavras obrigatórias/banidas.
- Persistência local em SQLite, com caminho baseado na pasta do script.
- Registro apenas de novas ofertas ou mudanças de preço e notificação nativa do Windows quando a regra de alerta for atendida.
- Um inicializador .bat portátil que use a pasta do próprio arquivo e documente como instalar as dependências e configurar o Agendador de Tarefas.
- Filtros e seletores verificados com uma execução manual; não assumir que seletores de outros sites são intercambiáveis.

Valores iniciais:
- Preço mínimo: [VALOR]
- Preço-alvo para alerta: [VALOR]
- Termos obrigatórios: [LISTA]
- Termos banidos: [LISTA]

Entregue também requirements.txt, README.md, .gitignore e documentação do fluxo e dos pontos que precisam de manutenção.
```
