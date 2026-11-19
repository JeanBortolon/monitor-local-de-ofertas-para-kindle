"""Coleta ofertas de Kindle, registra mudancas de preco e notifica no Windows.

Dependencias externas: Selenium controla o Chrome, webdriver-manager localiza o
ChromeDriver e winotify cria as notificacoes nativas. Os modulos restantes
(os, sqlite3, re, time, datetime e urllib.parse) pertencem ao Python.
"""

import os  # Monta caminhos locais e verifica/tamanho os arquivos de log.
import sqlite3  # Armazena o historico de precos em um banco SQLite local.
import re  # Interpreta precos e procura palavras inteiras nos titulos.
import time  # Aguarda a renderizacao das paginas dinamicas.
from datetime import datetime  # Registra o horario de cada rodada.
from urllib.parse import urlparse, urlunparse  # Divide e remonta URLs sem tracking.
from selenium import webdriver  # Abre e controla o navegador automatizado.
from selenium.common.exceptions import TimeoutException  # Identifica timeout de carregamento.
from selenium.webdriver.chrome.service import Service  # Configura o servico ChromeDriver.
from selenium.webdriver.chrome.options import Options  # Define opcoes do Chrome.
from selenium.webdriver.common.by import By  # Escolhe CSS/XPath para localizar elementos.
from webdriver_manager.chrome import ChromeDriverManager  # Localiza/instala o ChromeDriver.
from winotify import Notification, audio  # Cria notificacoes e configura seu som.

# Preco abaixo do qual o monitor presume que o resultado e um acessorio, nao o aparelho.
PRECO_MINIMO_REAL = 350.00
# Teto de preco para uma notificacao de oferta nova ou em queda.
PRECO_ALVO_ALERTA = 700.00

# Termos que descartam acessorios, itens defeituosos e produtos usados/recondicionados.
# A funcao produto_valido procura cada termo como palavra inteira usando Regex \b.
PALAVRAS_BANIDAS = [
    "capa", "capinha", "case", "película", "pelicula", "cabo", "suporte", "sleeve",
    "bateria", "adaptador", "carregador", "adesivo", "skin", "bolsa", "fonte",
    "quebrado", "defeito", "sucata", "caixa", "kobo", "lev",
    "livro", "e-book", "ebook", "guia", "manual", "usado", "vitrine", "recondicionado"
]

# Descobre a pasta do script, independente do diretorio em que o Agendador inicia o processo.
PASTA_ATUAL = os.path.dirname(os.path.abspath(__file__))
# Guarda o banco junto ao script para evitar criar outro em um diretorio de trabalho externo.
CAMINHO_BANCO = os.path.join(PASTA_ATUAL, "historico_kindle.db")
# Guarda o log de execucao no mesmo diretorio do projeto.
CAMINHO_LOG = os.path.join(PASTA_ATUAL, "execucoes.log")

def gerenciar_tamanho_log(max_bytes=500_000, manter_linhas=500):
    """Se o log passar do limite, conserva somente suas linhas mais recentes."""
    try:
        # A verificacao evita abrir o arquivo quando ele ainda nao existe.
        if os.path.exists(CAMINHO_LOG) and os.path.getsize(CAMINHO_LOG) > max_bytes:
            # Le o arquivo ignorando bytes que nao possam ser decodificados como UTF-8.
            with open(CAMINHO_LOG, "r", encoding="utf-8", errors="ignore") as f:
                linhas = f.readlines()
            # Sobrescreve o log com o sufixo que contem as execucoes mais recentes.
            with open(CAMINHO_LOG, "w", encoding="utf-8") as f:
                f.writelines(linhas[-manter_linhas:])
    except Exception:
        # Um problema de rotacao nao impede a busca principal de ofertas.
        pass

def iniciar_banco():
    # Abre/cria o banco local e aguarda ate 30 segundos se outro processo o estiver usando.
    conn = sqlite3.connect(CAMINHO_BANCO, timeout=30)
    # Cria um cursor para enviar comandos SQL.
    cursor = conn.cursor()
    # Cria a tabela apenas na primeira execucao; as seguintes preservam o historico existente.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ofertas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            loja TEXT,
            titulo TEXT,
            preco REAL,
            link TEXT,
            data_coleta TEXT
        )
    """)
    # Acelera a consulta do ultimo preco por loja e titulo.
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_loja_titulo ON ofertas (loja, titulo)")
    # Persiste a criacao da tabela e do indice.
    conn.commit()
    # Retorna a conexao para consultas e insercoes durante a varredura.
    return conn

def normalizar_link(url):
    """Remove fragmento, query e sufixos /ref= para reduzir links duplicados."""
    # Devolve texto vazio quando o site nao forneceu um destino.
    if not url:
        return ""
    # Separa protocolo, dominio, caminho e demais partes da URL.
    parsed = urlparse(url)
    # Remove o marcador de referencia da Amazon que possa estar no caminho.
    caminho = re.sub(r'/ref=.*$', '', parsed.path)
    # Remonta o endereco mantendo apenas protocolo, dominio e caminho limpo.
    return urlunparse((parsed.scheme, parsed.netloc, caminho, '', '', ''))

def obter_ultimo_preco(cursor, loja, titulo):
    """Busca o registro de preco mais recente para o mesmo portal e titulo."""
    # Remove o nome da loja parceira entre parenteses, como "Zoom (Loja X)".
    portal_base = loja.split(" (")[0].strip()
    # Consulta o registro mais novo daquele titulo na mesma fonte base.
    cursor.execute("""
        SELECT preco FROM ofertas 
        WHERE loja LIKE ? AND titulo = ? 
        ORDER BY id DESC LIMIT 1
    """, (f"{portal_base}%", titulo))
    # Le a primeira linha retornada pela ordenacao descendente de id.
    resultado = cursor.fetchone()
    # Retorna o preco se houver historico; caso contrario, sinaliza produto novo.
    return resultado[0] if resultado else None

def configurar_driver():
    # Cria o objeto de configuracao do Chrome antes de iniciar o navegador.
    options = Options()
    # Executa sem abrir uma janela visivel no desktop.
    options.add_argument("--headless=new")
    # Desativa aceleracao grafica, desnecessaria na coleta sem interface.
    options.add_argument("--disable-gpu")
    # Permite execucao em ambientes Linux de container; no Windows nao e necessario.
    options.add_argument("--no-sandbox")
    # Define dimensoes consistentes para que o layout responsivo seja previsivel.
    options.add_argument("--window-size=1920,1080")
    # Ajusta uma flag do Chrome que costuma alterar elementos expostos pelo navegador.
    options.add_argument("--disable-blink-features=AutomationControlled")
    # Define o user-agent enviado pelo navegador as paginas.
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
    # Evita avisos e marcas de automacao na interface do Chrome.
    options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
    # Desativa a extensao de automacao legada do Chrome.
    options.add_experimental_option("useAutomationExtension", False)
    
    # Encontra ou instala uma versao compativel do ChromeDriver.
    servico = Service(ChromeDriverManager().install())
    # Inicia o Chrome usando o servico e as opcoes definidos acima.
    driver = webdriver.Chrome(service=servico, options=options)
    # Limita o tempo de espera por carregamento de cada pagina a 25 segundos.
    driver.set_page_load_timeout(25)
    
    # Executa uma pequena configuracao no contexto de cada documento carregado.
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    })
    # Devolve o navegador pronto para as funcoes de busca.
    return driver

def acessar_url_segura(driver, url):
    """Acessa uma pagina e trata timeout/erro sem encerrar toda a coleta."""
    try:
        # Navega para a URL fornecida.
        driver.get(url)
        # Aguarda a pagina completar parte da renderizacao dinamica.
        time.sleep(4)
        # Indica que a navegacao terminou dentro do tempo esperado.
        return True
    except TimeoutException:
        # O Chrome pode ter carregado conteudo suficiente mesmo apos o timeout.
        print(f"   [Aviso] Tempo limite de 25s atingido em {url}, lendo conteúdo carregado...")
        return True
    except Exception as e:
        # Registra o erro e informa ao chamador para ignorar esta fonte.
        print(f"   [Erro] Falha ao acessar {url}: {e}")
        return False

def limpar_preco(texto_preco):
    # Sem texto de preco nao ha valor numerico confiavel para extrair.
    if not texto_preco:
        return None
    # Reduz quebras de linha e espacos que atrapalham a expressao regular.
    texto_limpo = texto_preco.replace("\n", " ").strip()
    # Extrai formatos brasileiros como 1.299,90 ou 499.
    padrao = re.search(r"(\d{1,3}(?:\.\d{3})*(?:,\d{2})?)", texto_limpo)
    if padrao:
        # Remove separador de milhar e troca a virgula decimal por ponto.
        valor_limpo = padrao.group(1).replace(".", "").replace(",", ".")
        # Converte o texto normalizado em numero decimal.
        return float(valor_limpo)
    # Retorna None quando o texto nao contem um preco reconhecido.
    return None

def produto_valido(titulo, preco):
    # Descarta titulo/preco ausente, preco zero ou preco abaixo do piso configurado.
    if not titulo or not preco or preco < PRECO_MINIMO_REAL:
        return False
    # Padroniza caixa para tornar a busca por palavras independente de maiusculas.
    titulo_lower = titulo.lower()
    # Exige que o nome do produto monitorado esteja presente.
    if "kindle" not in titulo_lower:
        return False
    for banida in PALAVRAS_BANIDAS:
        # A fronteira \b impede que, por exemplo, "case" case dentro de outra palavra.
        if re.search(rf"\b{re.escape(banida)}\b", titulo_lower):
            return False
    # O titulo passou pelo termo obrigatorio e por todas as palavras de exclusao.
    return True

def notificar_windows(loja, titulo, preco, preco_anterior, link):
    try:
        # Diferencia uma oferta nova de uma reducao em produto ja acompanhado.
        if preco_anterior:
            titulo_notif = f"📉 Baixou na {loja}: R$ {preco:.2f} (Era R$ {preco_anterior:.2f})"
        else:
            titulo_notif = f"🔥 Nova Oferta ({loja}): R$ {preco:.2f}"
            
        # Monta uma notificacao nativa curta com nome do monitor, titulo e preco.
        toast = Notification(
            app_id="Monitor de Ofertas Kindle",
            title=titulo_notif,
            msg=titulo[:80],
            duration="short"
        )
        # Usa o som padrao do Windows sem repetir em loop.
        toast.set_audio(audio.Default, loop=False)
        # Inclui um botao que abre o link da oferta ao ser clicado.
        toast.add_actions(label="Abrir Oferta", launch=link)
        # Envia a notificacao ao sistema operacional.
        toast.show()
    except Exception as e:
        # A falha de notificacao e exibida, mas nao interrompe a gravacao do historico.
        print(f"[Aviso] Erro na notificação: {e}")

def buscar_amazon(driver):
    """Extrai cards de produtos da pagina de busca da Amazon Brasil."""
    # Informa no console qual etapa esta sendo executada.
    print("-> [1/5] Buscando na Amazon Brasil...")
    # Acumula tuplas no formato loja, titulo, preco e link.
    ofertas = []
    # Abre a busca; se falhar, devolve a lista vazia sem interromper as outras fontes.
    if not acessar_url_segura(driver, "https://www.amazon.com.br/s?k=kindle"):
        return ofertas
    
    # Localiza os cards de resultado de busca da Amazon.
    cards = driver.find_elements(By.CSS_SELECTOR, "div[data-component-type='s-search-result']")
    for card in cards:
        try:
            # Le o titulo dentro do cabecalho do card.
            titulo = card.find_element(By.CSS_SELECTOR, "h2").text.strip()
            # Le a parte inteira do preco exibida pela Amazon.
            preco_inteiro = card.find_element(By.CSS_SELECTOR, "span.a-price-whole").text.strip()
            try:
                # Quando disponivel, combina tambem os centavos.
                preco_centavos = card.find_element(By.CSS_SELECTOR, "span.a-price-fraction").text.strip()
                preco_completo = f"{preco_inteiro},{preco_centavos}"
            except Exception:
                # Alguns cards nao exibem centavos; nesse caso usa apenas a parte inteira.
                preco_completo = preco_inteiro
                
            # Normaliza o texto do preco e remove parametros do link.
            preco = limpar_preco(preco_completo)
            link = normalizar_link(card.find_element(By.CSS_SELECTOR, "a.a-link-normal").get_attribute("href"))
            
            # Adiciona somente produtos que passaram pelos filtros do monitor.
            if produto_valido(titulo, preco):
                ofertas.append(("Amazon", titulo, preco, link))
        except Exception:
            # Ignora cards incompletos/inesperados e continua com os demais resultados.
            continue
    # Mostra a quantidade final coletada nessa fonte.
    print(f"   Encontrados na Amazon: {len(ofertas)} ofertas válidas.")
    # Retorna os resultados para consolidacao na varredura principal.
    return ofertas

def buscar_kalunga(driver):
    """Extrai os resultados da busca de Kindle na Kalunga."""
    print("-> [2/5] Buscando na Kalunga...")
    ofertas = []
    # Abre a pagina de resultados da Kalunga.
    if not acessar_url_segura(driver, "https://www.kalunga.com.br/busca/1?q=kindle"):
        return ofertas
    
    # Seleciona os containers dos produtos.
    cards = driver.find_elements(By.CSS_SELECTOR, "div.blocoproduto")
    for card in cards:
        try:
            # Encontra o link que contem titulo e destino do produto.
            link_elem = card.find_element(By.CSS_SELECTOR, "a.blocoproduto__link")
            # Prefere o atributo title; usa o texto visivel como alternativa.
            titulo = (link_elem.get_attribute("title") or link_elem.text).strip()
            # Normaliza o endereco antes de armazenar.
            link = normalizar_link(link_elem.get_attribute("href"))
            
            # Le e converte o preco exibido no card.
            preco_str = card.find_element(By.CSS_SELECTOR, "span.blocoproduto__price").text
            preco = limpar_preco(preco_str)
            
            # Guarda somente titulos e precos aprovados pelo filtro comum.
            if produto_valido(titulo, preco):
                ofertas.append(("Kalunga", titulo, preco, link))
        except Exception:
            # Pula cards que nao tenham os campos esperados.
            continue
    print(f"   Encontrados na Kalunga: {len(ofertas)} ofertas válidas.")
    return ofertas

def buscar_pelando(driver):
    """Extrai ofertas de Kindle publicadas nos resultados de busca do Pelando."""
    print("-> [3/5] Buscando no Pelando (Ofertas da Shopee, ML, Magalu, etc.)...")
    ofertas = []
    # Abre a busca por Kindle no Pelando.
    if not acessar_url_segura(driver, "https://www.pelando.com.br/busca/kindle"):
        return ofertas
    
    # Rola a página para garantir a renderização dos cards dinâmicos (React/Next.js)
    try:
        # Desloca a pagina para carregar conteudo que aparece ao rolar.
        driver.execute_script("window.scrollBy(0, 800);")
        # Aguarda a insercao dos novos cards no documento.
        time.sleep(2)
    except Exception:
        # A rolagem e apenas uma tentativa; a busca continua mesmo sem ela.
        pass
        
    # Recolhe links de discussoes/ofertas e prepara deduplicacao local.
    links_elems = driver.find_elements(By.CSS_SELECTOR, "a[href*='/d/']")
    links_processados = set()
    
    for a in links_elems:
        try:
            # Le o destino; sem href nao ha oferta navegavel.
            href = a.get_attribute("href")
            if not href:
                continue
            # Limpa parametros de rastreamento e ignora links repetidos.
            link = normalizar_link(href)
            if link in links_processados:
                continue
                
            # Usa o atributo title, se disponivel, ou o texto visivel do link.
            titulo_bruto = (a.get_attribute("title") or a.text).strip()
            # Descarta textos curtos demais para representar um titulo.
            if len(titulo_bruto) < 6:
                continue
                
            # Se o link englobar múltiplas linhas de texto, isola a linha do título do Kindle
            linhas_titulo = [l.strip() for l in titulo_bruto.split("\n") if "kindle" in l.lower()]
            titulo = linhas_titulo[0] if linhas_titulo else titulo_bruto.split("\n")[0].strip()
            
            # Sobe na árvore HTML a partir do link até localizar o container completo do card com preço
            card_elem = a
            texto_card = ""
            for _ in range(6):
                # Inspeciona o texto do elemento atual procurando preco e tamanho plausivel.
                t = card_elem.text
                if "R$" in t and len(t) < 800:
                    texto_card = t
                    break
                # Sobe um nivel no DOM para encontrar o container que agrupa o card.
                card_elem = card_elem.find_element(By.XPATH, "..")
                
            # Sem container/preco identificavel, nao ha dados suficientes para o registro.
            if not texto_card:
                continue
                
            # Marca o endereco como tratado para evitar ler o mesmo card novamente.
            links_processados.add(link)
            texto_card_lower = texto_card.lower()
            
            # Ignora promoções passadas que aparecem na busca marcadas como "Inativa" ou "Encerrada"
            if any(status in texto_card_lower for status in ["inativ", "encerrad", "expirad", "esgotad"]):
                continue
                
            # Extrai o valor em reais do texto do card, se houver.
            match_preco = re.search(r"R\$\s?(\d{1,3}(?:\.\d{3})*(?:,\d{2})?)", texto_card)
            preco = limpar_preco(match_preco.group(1)) if match_preco else None
            
            # Inclui a oferta somente se produto, preco e palavras forem validos.
            if produto_valido(titulo, preco):
                ofertas.append(("Pelando", titulo, preco, link))
        except Exception:
            # Um card malformado nao deve impedir a leitura dos demais.
            continue
            
    print(f"   Encontrados no Pelando: {len(ofertas)} ofertas ativas válidas.")
    return ofertas

def buscar_zoom(driver):
    """Extrai produtos e loja parceira dos cards de busca do Zoom."""
    print("-> [4/5] Buscando no Zoom (Magalu, KaBuM, Fast Shop, etc.)...")
    ofertas = []
    # Abre a busca no Zoom.
    if not acessar_url_segura(driver, "https://www.zoom.com.br/search?q=kindle"):
        return ofertas
    
    # Localiza cards pela identificacao de teste usada pela pagina.
    cards = driver.find_elements(By.CSS_SELECTOR, "[data-testid='product-card']")
    for card in cards:
        try:
            # Le o nome, preco e link do produto no card.
            titulo = card.find_element(By.CSS_SELECTOR, "[data-testid='product-card::name']").text.strip()
            preco_str = card.find_element(By.CSS_SELECTOR, "[data-testid='product-card::price']").text
            preco = limpar_preco(preco_str)
            link = normalizar_link(card.find_element(By.CSS_SELECTOR, "a").get_attribute("href"))
            
            # Usa Zoom como nome padrao ate encontrar o nome do vendedor parceiro.
            loja_parceira = "Zoom"
            try:
                # O texto de descricao pode identificar o parceiro que fornece a oferta.
                desc_loja = card.find_element(By.CSS_SELECTOR, "[data-testid='product-card::description']").text
                if " via " in desc_loja.lower():
                    # Registra o parceiro entre parenteses junto ao portal de origem.
                    loja_parceira = f"Zoom ({desc_loja.split('via')[-1].strip()})"
            except Exception:
                # A descricao do parceiro e opcional, portanto o nome base continua valido.
                pass
                
            # Guarda os campos somente se o resultado passar pelo filtro de produto.
            if produto_valido(titulo, preco):
                ofertas.append((loja_parceira, titulo, preco, link))
        except Exception:
            # Ignora cards que nao correspondam ao layout esperado.
            continue
    print(f"   Encontrados no Zoom: {len(ofertas)} ofertas válidas.")
    return ofertas

def buscar_buscape(driver):
    """Extrai produtos e loja parceira dos cards de busca do Buscape."""
    print("-> [5/5] Buscando no Buscapé (Várias Lojas)...")
    ofertas = []
    # Abre a busca de Kindle no Buscape.
    if not acessar_url_segura(driver, "https://www.buscape.com.br/search?q=kindle"):
        return ofertas
    
    # Encontra cards de produto por seu atributo data-testid.
    cards = driver.find_elements(By.CSS_SELECTOR, "[data-testid='product-card']")
    for card in cards:
        try:
            # Le nome, preco e URL do produto no card.
            titulo = card.find_element(By.CSS_SELECTOR, "[data-testid='product-card::name']").text.strip()
            preco_str = card.find_element(By.CSS_SELECTOR, "[data-testid='product-card::price']").text
            preco = limpar_preco(preco_str)
            link = normalizar_link(card.find_element(By.CSS_SELECTOR, "a").get_attribute("href"))
            
            # Define o nome-base do portal enquanto nao encontra um vendedor.
            loja_parceira = "Buscapé"
            try:
                # Busca uma descricao opcional que pode conter o nome do parceiro.
                desc_loja = card.find_element(By.CSS_SELECTOR, "[data-testid='product-card::description']").text
                if " via " in desc_loja.lower():
                    # Registra o parceiro para diferenciar a loja na consulta do historico.
                    loja_parceira = f"Buscapé ({desc_loja.split('via')[-1].strip()})"
            except Exception:
                # A ausencia da descricao nao invalida o preco e o titulo do produto.
                pass
                
            # Armazena resultados aprovados pelo filtro comum.
            if produto_valido(titulo, preco):
                ofertas.append((loja_parceira, titulo, preco, link))
        except Exception:
            # Continua a leitura mesmo que um dos cards esteja incompleto.
            continue
    print(f"   Encontrados no Buscapé: {len(ofertas)} ofertas válidas.")
    return ofertas

def executar_varredura():
    """Executa uma rodada completa e garante o fechamento dos recursos."""
    # Reduz o tamanho do log antes de acrescentar novas mensagens.
    gerenciar_tamanho_log()
    # Formata a data/hora usada nos registros e no console.
    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n=== [{agora}] Iniciando Monitoramento Inteligente de Kindle ===")
    
    # Abre o banco e cria o cursor que sera reutilizado nas consultas/insercoes.
    conn = iniciar_banco()
    cursor = conn.cursor()
    # Inicializa a variavel para verificar no finally se o navegador chegou a abrir.
    driver = None
    
    try:
        # Cria o navegador headless para reutilizar em todas as fontes desta rodada.
        driver = configurar_driver()
        # Reune numa lista os resultados retornados por cada scraper.
        resultados = []
        resultados.extend(buscar_amazon(driver))
        resultados.extend(buscar_kalunga(driver))
        resultados.extend(buscar_pelando(driver))
        resultados.extend(buscar_zoom(driver))
        resultados.extend(buscar_buscape(driver))
        
        # Agrupa pelo portal base + título para manter apenas o menor preço da rodada
        # A chave remove a loja parceira entre parenteses para comparar o mesmo portal.
        ofertas_unicas = {}
        for loja, titulo, preco, link in resultados:
            portal_base = loja.split(" (")[0].strip()
            chave = (portal_base, titulo)
            # Atualiza o dicionario se for o primeiro resultado ou se este for mais barato.
            if chave not in ofertas_unicas or preco < ofertas_unicas[chave][2]:
                ofertas_unicas[chave] = (loja, titulo, preco, link)
                
        # Ordena as ofertas consolidadas do menor para o maior preco.
        lista_final = sorted(ofertas_unicas.values(), key=lambda x: x[2])
        print(f"\nTotal de ofertas únicas nesta rodada: {len(lista_final)}\n")
        
        # Conta insercoes feitas para resumir a execucao.
        novos_registros = 0
        
        for loja, titulo, preco, link in lista_final:
            # Busca o preco mais recente do mesmo titulo na fonte-base.
            ultimo_preco = obter_ultimo_preco(cursor, loja, titulo)
            
            # Grava apenas produtos novos ou cujo preco difere do ultimo valor salvo.
            if ultimo_preco is None or preco != ultimo_preco:
                # Usa parametros SQL para inserir valores com seguranca e formato correto.
                cursor.execute(
                    "INSERT INTO ofertas (loja, titulo, preco, link, data_coleta) VALUES (?, ?, ?, ?, ?)",
                    (loja, titulo, preco, link, agora)
                )
                # Atualiza o total de mudancas inseridas.
                novos_registros += 1
                # Prepara um texto de status para o log desta oferta.
                status_str = "NOVO" if ultimo_preco is None else f"MUDOU (Era R$ {ultimo_preco:.2f})"
                print(f"[{status_str}] [{loja}] R$ {preco:.2f} | {titulo[:45]}...")
                
                # Notifica se esta dentro do teto e e nova ou uma reducao real.
                if preco <= PRECO_ALVO_ALERTA and (ultimo_preco is None or preco < ultimo_preco):
                    notificar_windows(loja, titulo, preco, ultimo_preco, link)
            else:
                # Informa que o preco nao mudou e evita uma nova linha redundante.
                print(f"[MANTIDO] [{loja}] R$ {preco:.2f} | {titulo[:45]}...")
                
        # Confirma todas as insercoes feitas durante esta varredura.
        conn.commit()
        print(f"\n=== [{agora}] Concluído! {novos_registros} alterações registradas em historico_kindle.db ===")
    finally:
        # Fecha o Chrome mesmo quando a coleta ou banco geram uma excecao.
        if driver:
            driver.quit()
        # Fecha a conexao SQLite para liberar o arquivo e seus bloqueios.
        conn.close()

if __name__ == "__main__":
    # Inicia uma rodada somente quando este arquivo for executado diretamente.
    executar_varredura()