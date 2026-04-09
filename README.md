🚀 Arquitetura de Deploy Automatizado SRE - TOTVS Protheus

Este pipeline foi desenhado para resolver o maior problema de deploy no Protheus: compilar milhares de fontes e atualizar dezenas de serviços (AppServers) em produção sem gerar indisponibilidade (Zero-Downtime) e sem travamentos de compilação.

Aqui está o passo a passo de como o "motor" funciona:

🛠️ Passo 0: Atualização do Workspace (Git)
O processo começa garantindo que o código a ser compilado é a versão mais recente e oficial.
* O script Python se conecta ao repositório Git corporativo usando um Token de segurança.
* Ele força um checkout na branch correta (ex: master) e faz um pull (download) de todos os códigos-fonte (.prw, .tlpp, etc.) para uma pasta local de Workspace.

🗺️ Passo 1: Mapeamento Inteligente de Ambientes
O script precisa saber quem está rodando o quê, sem que um humano precise informar.
* Ele varre a pasta bin do servidor buscando todos os arquivos appserver*.ini.
* A Trava de Segurança SRE: Ele ignora propositalmente a pasta do binário usado para compilação (para não quebrar o motor) e foca apenas nos serviços de produção.
* Ele lê cada .ini para descobrir qual é a pasta de RPO atual em uso (ex: APO_R1) e calcula matematicamente qual será a próxima pasta de destino na rotação (ex: Se está na R1, a próxima é R2. O ciclo roda de R1 até R4 e volta pro R1).

📦 Passo 1.5: Preparação do "Bunker" de Compilação (Staging)
Nunca se compila diretamente no RPO que está em uso pelo serviço ativo.
* O script elege um ambiente "Fonte da Verdade" (geralmente o ambiente de compilação oficial).
* Ele copia os arquivos tttm120.rpo e custom.rpo desse ambiente para uma pasta isolada chamada APO_PCOMPILA. 
* Essa pasta funciona como uma "sala limpa". Toda a compilação vai acontecer aqui, garantindo que a produção fique intacta se algo der errado.

⚙️ Passo 2: Injeção de Código via TDS-CLI (O Motor)
Aqui acontece a mágica para evitar os famosos travamentos (Content-Length / Erro 61).
* O script gera dinamicamente um arquivo compile.ini (JSON/INI Mode) com a lista de todos os milhares de fontes encontrados no Passo 0.
* Ele "acorda" o binário do Protheus (advpls.exe em modo cli) passando esse arquivo de lote. 
* O motor compila todos os fontes de uma só vez apontando para o nosso RPO isolado (APO_PCOMPILA), com performance máxima e sem abrir portas de comunicação (RPC) que causam travamentos no Windows.

🚚 Passo 3: Distribuição (Hot-Swap Target)
Com o RPO recém-compilado e atualizado na pasta APO_PCOMPILA, é hora de distribuir.
* O script pega esse novo RPO e o copia para a próxima pasta da rotação de cada ambiente mapeado no Passo 1 (ex: copia para a pasta APO_R2).
* Como a pasta APO_R2 ainda "não existe" para o AppServer (que está lendo a R1), a cópia acontece sem nenhum erro de arquivo em uso (File Lock).

🔄 Passo 4: A Virada de Chave (Atualização dos INIs)
É aqui que o deploy efetivamente entra em produção.
* O script abre cada um dos arquivos appserver.ini dos serviços.
* Ele procura a linha do SourcePath que aponta para a pasta antiga (APO_R1), e coloca um # na frente (comenta a linha).
* Ele procura a linha do SourcePath que aponta para a pasta nova (APO_R2) e tira o # (descomenta a linha).
* Resultado: Na próxima vez que o serviço for reiniciado (ou quando as threads forem recicladas), o Protheus passará a ler o RPO novo automaticamente.

✅ Passo 5: Validação e Dashboard SRE
Um processo automatizado não é SRE se não tiver auditoria.
* O script faz uma re-leitura de todos os arquivos .ini alterados para validar sintaticamente se a virada de chave ocorreu perfeitamente e se não há linhas duplicadas.
* Por fim, ele cospe no console (e em um arquivo de log) um Resumo Executivo contendo:
  * A branch do Git utilizada.
  * Quantos fontes foram compilados.
  * Uma tabela mostrando Serviço por Serviço: qual era o RPO antigo, qual é o novo, e o Status Final (OK/FALHA).
