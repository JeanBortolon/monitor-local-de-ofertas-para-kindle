# Monitor local de ofertas Kindle

Script Python para consultar ofertas de Kindle na Amazon Brasil, Kalunga, Pelando, Zoom e Buscapé. O Selenium abre as páginas em modo headless, os resultados válidos são guardados no SQLite local e uma notificação do Windows é exibida para uma oferta nova ou com queda de preço dentro do limite configurado.

> Os sites podem mudar seus layouts, seletores ou regras de acesso. O monitor não garante que todas as ofertas serão encontradas; use os sites de acordo com seus termos e respeite eventuais limites de acesso.

## O que o programa faz

- Consulta as cinco fontes configuradas em `kindle.py`.
- Filtra resultados por preço mínimo, pelo termo `kindle` e por uma lista de palavras excluídas.
- Normaliza links e agrupa resultados da mesma fonte e título, mantendo o menor preço encontrado naquela rodada.
- Armazena mudanças de preço na tabela `ofertas` de `historico_kindle.db`.
- Mostra uma notificação nativa do Windows quando o preço está no limite configurado e é novo ou menor que o último preço registrado.
- Mantém o arquivo de log sob controle de tamanho; o inicializador também direciona a saída do programa para `execucoes.log`.

## Arquivos

```text
kindle.py          Script de coleta, filtragem, histórico e notificações.
rodar_kindle.bat   Inicializador do Windows; usa Python disponível no PATH.
requirements.txt   Dependências externas de Python.
historico_kindle.db  Banco SQLite criado automaticamente na primeira execução.
execucoes.log      Log local criado pelo arquivo .bat.
CONTEXT.md         Notas para adaptar a arquitetura a outros produtos.
.gitignore         Exclui dados e arquivos locais gerados do Git.
```

O banco e o log existentes são dados locais e estão excluídos pelo `.gitignore`; a exclusão do Git não apaga os arquivos do computador.

## Requisitos

- Windows 10/11.
- Python 3.10 ou superior, acessível como `python` no `PATH`.
- Google Chrome instalado.

`webdriver-manager` pode precisar baixar ou localizar um ChromeDriver compatível na primeira execução, com acesso à internet.

## Instalação e execução

Abra o PowerShell na pasta do projeto e instale as dependências:

```powershell
python -m pip install -r requirements.txt
```

Execute manualmente:

```powershell
.\rodar_kindle.bat
```

O `.bat` usa a pasta em que está salvo, então pode ser movido junto com o projeto. Ele procura `python` no `PATH`; se o comando não for encontrado, adicione a instalação do Python ao `PATH` ou ajuste o inicializador para apontar para `python.exe`.

## Configuração da busca

No começo de `kindle.py`, ajuste:

- `PRECO_MINIMO_REAL`: descarta produtos abaixo desse valor, normalmente acessórios.
- `PRECO_ALVO_ALERTA`: teto para uma notificação de oferta.
- `PALAVRAS_BANIDAS`: palavras que fazem um resultado ser descartado.

O termo de busca `kindle`, as URLs e os seletores de cada site estão dentro das funções `buscar_*`. Para monitorar outro produto, além dos valores e palavras, adapte essas funções e a validação `produto_valido`; as fontes atuais têm HTML e formatos de resultado próprios. Consulte também `CONTEXT.md`.

## Agendador de Tarefas do Windows

Crie uma tarefa e, em **Ações > Iniciar um programa**, configure:

- **Programa/script:** caminho completo para `rodar_kindle.bat` (entre aspas se o caminho tiver espaços).
- **Adicionar argumentos:** deixe vazio.
- **Iniciar em:** caminho da pasta do projeto.

Escolha a frequência desejada e confirme que a tarefa pode executar com a conta do Windows que receberá as notificações. Uma sessão de usuário conectada pode ser necessária para que as notificações apareçam.

## Banco de dados

O banco SQLite é criado ao lado de `kindle.py`. A tabela `ofertas` guarda loja, título, preço, link e data de coleta. Para consultar no DBeaver, conecte ao arquivo `historico_kindle.db` e execute, por exemplo:

```sql
SELECT
    loja,
    titulo,
    MIN(preco) AS menor_preco_historico,
    MAX(preco) AS maior_preco_registrado,
    COUNT(*) AS mudancas_de_preco,
    link
FROM ofertas
GROUP BY loja, titulo
ORDER BY menor_preco_historico ASC;
```

Para ver registros abaixo do limite atual de R$ 700:

```sql
SELECT id, loja, titulo, preco, data_coleta, link
FROM ofertas
WHERE preco <= 700.00
ORDER BY data_coleta DESC, preco ASC;
```

Altere `700.00` na consulta se mudar `PRECO_ALVO_ALERTA`.

## Dependências

- `selenium`: controla o navegador Chrome e localiza os elementos das páginas.
- `webdriver-manager`: auxilia na instalação/localização do ChromeDriver.
- `winotify`: cria notificações nativas do Windows.
- `sqlite3`, `os`, `re`, `time`, `datetime` e `urllib.parse`: módulos da biblioteca padrão do Python, usados respectivamente para banco, caminhos/arquivos, expressões regulares, pausas, datas e tratamento de URLs.

As dependências de terceiros estão listadas em `requirements.txt`; módulos da biblioteca padrão não precisam ser instalados com pip.
