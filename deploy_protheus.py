import os
import sys
import logging
import subprocess
import shutil
from datetime import datetime

# --- LEITURA DO ARQUIVO: credenciais.env ---
def ler_config_file():
    configs = {}
    pasta_atual = os.getcwd()
    arquivo = os.path.join(pasta_atual, 'credenciais.env')
    if not os.path.exists(arquivo):
        print(f"\n[ERRO] Arquivo 'credenciais.env' NAO encontrado.")
        return configs
    try:
        with open(arquivo, 'r', encoding='utf-8-sig') as f:
            for linha in f:
                linha = linha.strip()
                if linha and not linha.startswith('#') and '=' in linha:
                    chave, valor = linha.split('=', 1)
                    configs[chave.strip()] = valor.strip()
    except Exception as e:
        print(f"Erro ao ler credenciais: {e}")
    return configs

config = ler_config_file()

# --- EXTRAÇÃO DAS CREDENCIAIS E CONFIGURAÇÕES ---
TOKEN = config.get("GIT_TOKEN", "")
TDS_USER = config.get("TDS_USER", "usuário protheus")
TDS_PWD = config.get("TDS_PWD", "senha protheus")
GIT_BRANCH = config.get("GIT_BRANCH", "master") 

SOURCE_WORKSPACE = r"C:\Protheus\protheus-sistema"
BASE_BIN_DIR = r"E:\TOTVS\TOTVS_PRODUCAO\bin"
BASE_APO_DIR = r"E:\TOTVS\TOTVS_PRODUCAO\apo"
DIR_PCOMPILA = os.path.join(BASE_APO_DIR, "APO_PCOMPILA")

GIT_URL = f"http://oauth2:{TOKEN}@git.valecard.com.br/protheus/protheus-sistema.git"

INCLUDE_DIR = r"E:\include_v12"
TDS_CLI_PATH = r"E:\TOTVS\TOTVS_PRODUCAO\Deploy\tds-ls-master\advpls.exe" 

BUILD_SERVER = "ip server"
BUILD_PORT = porta_server
BUILD_ENV = "PSLV16_COMP"
BUILD_VERSION = "7.00.240223P"

fontes_compilados_qtd = 0

log_name = f"deploy_sre_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s',
                    handlers=[logging.FileHandler(log_name), logging.StreamHandler(sys.stdout)])

# --- LÓGICA DE RPO (TROCA QUENTE E CICLO R1->R4) ---
def get_next_rpo(current_rpo):
    c = current_rpo.upper()
    # Mapeamento direto para a base
    if c == 'APO_R1': return 'APO_R2'
    if c == 'APO_R2': return 'APO_R3'
    if c == 'APO_R3': return 'APO_R4'
    if c == 'APO_R4': return 'APO_R1'
    
    # Mapeamento para os sufixos (JOBS, PWEB, etc)
    if c.endswith('_R2'): return c.replace('_R2', '_R3')
    if c.endswith('_R3'): return c.replace('_R3', '_R4')
    if c.endswith('_R4'): return c.replace('_R4', '') # Volta do 4 para o 1 (Sem sufixo)
    
    return c + '_R2' # Vai do 1 (Sem sufixo) para o 2

def update_git_workspace():
    logging.info("--- PASSO 0: ATUALIZANDO WORKSPACE (GIT) ---")
    if not TOKEN:
        logging.error("TOKEN NAO ENCONTRADO no credenciais.env")
        return False
    try:
        subprocess.run(["git", "remote", "set-url", "origin", GIT_URL], cwd=SOURCE_WORKSPACE, check=True, capture_output=True)
        logging.info("Buscando atualizações...")
        subprocess.run(["git", "fetch", "origin"], cwd=SOURCE_WORKSPACE, check=True, capture_output=True)
        logging.info(f"Checkout na branch: '{GIT_BRANCH}'...")
        subprocess.run(["git", "checkout", GIT_BRANCH], cwd=SOURCE_WORKSPACE, check=True, capture_output=True)
        
        logging.info("Fazendo PULL (Atualizando arquivos)...")
        pull_result = subprocess.run(["git", "pull", "origin", GIT_BRANCH], cwd=SOURCE_WORKSPACE, check=True, capture_output=True, text=True, encoding='utf-8')
        
        logging.info("SUCESSO: Git atualizado.")
        for line in pull_result.stdout.splitlines():
            if line.strip(): logging.info(f"  [GIT] {line.strip()}")
        return True
    except Exception as e:
        logging.error(f"ABORTANDO: Falha ao atualizar o Git. Conflito ou sem acesso: {e}")
        return False

def analyze_environments():
    logging.info("--- PASSO 1: MAPEAMENTO DE AMBIENTES (INIs) ---")
    env_map = {}
    if not os.path.exists(BASE_BIN_DIR):
        logging.error(f"Diretório base não encontrado: {BASE_BIN_DIR}")
        return env_map

    # Trava de Segurança SRE: O diretório exclusivo do compilador
    COMPILER_DIR = r"E:\TOTVS\TOTVS_PRODUCAO\bin\appserver_pslv16".lower()

    for root, dirs, files in os.walk(BASE_BIN_DIR):
        # Ignora pastas de broker E ignora estritamente a pasta do compilador
        dirs[:] = [d for d in dirs if "broker" not in d.lower() and os.path.join(root, d).lower() != COMPILER_DIR]
        
        for file in files:
            if file.lower().endswith('.ini') and file.lower().startswith('appserver'):
                path = os.path.join(root, file)
                try:
                    with open(path, 'r', encoding='latin-1') as f:
                        for line in f:
                            if not line.strip().startswith("#") and ("SourcePath=" in line or "RPOCustom=" in line):
                                if "APO_PCOMPILA" in line: continue
                                dir_path = line.split('=')[1].split(';')[0].strip().rstrip('\\')
                                current = os.path.basename(dir_path).upper()
                                nxt = get_next_rpo(current)
                                env_map[path] = {'current': current, 'next': nxt}
                                logging.info(f"INI Localizado: {file:<25} | Em Uso: {current:<12} | Proximo: {nxt}")
                                break 
                except Exception as e:
                    logging.warning(f"Erro ao ler {path}: {e}")
    return env_map

def prepare_base_rpo(env_map):
    logging.info("--- PASSO 1.5: PREPARANDO BASE DE COMPILACAO (RPO ATUAL) ---")
    target_rpo_dir = None
    target_ini = None
    
    for ini_path, info in env_map.items():
        if "pslv1" in ini_path.lower() and "comp" not in ini_path.lower():
            target_rpo_dir = info['current']
            target_ini = ini_path
            break
            
    if not target_rpo_dir and env_map:
        target_ini = list(env_map.keys())[0]
        target_rpo_dir = env_map[target_ini]['current']
        logging.warning(f"'pslv1' não detectado pelo nome. Usando {os.path.basename(target_ini)} como base.")

    if not target_rpo_dir:
        logging.error("Nenhum ambiente mapeado para extrair o RPO base.")
        return False
        
    logging.info(f"Fonte da Verdade: {os.path.basename(target_ini)} (Extraindo de: {target_rpo_dir})")
    
    src_dir = os.path.join(BASE_APO_DIR, target_rpo_dir)
    os.makedirs(DIR_PCOMPILA, exist_ok=True)
    
    rpos_to_copy = ["tttm120.rpo", "custom.rpo"]
    for rpo in rpos_to_copy:
        src_file = os.path.join(src_dir, rpo)
        dst_file = os.path.join(DIR_PCOMPILA, rpo)
        
        if os.path.exists(src_file):
            logging.info(f"Copiando base: {src_file} -> {dst_file}")
            shutil.copy2(src_file, dst_file)
        else:
            logging.warning(f"Arquivo não encontrado (Normal se não houver custom): {src_file}")
            
    return True

class TDSCompiler:
    def __init__(self):
        self.logs_dir = os.path.join(os.getcwd(), 'logs')
        os.makedirs(self.logs_dir, exist_ok=True)

    def get_compile_targets(self, workspace_path):
        if not os.path.isdir(workspace_path): return workspace_path.replace('\\', '/')
        valid_extensions = ['.prw', '.prx', '.tlpp', '.apw', '.aph', '.ahu']
        targets = []
        for item in os.listdir(workspace_path):
            if item.startswith('.'): continue
            full_path = os.path.join(workspace_path, item)
            if os.path.isfile(full_path) and os.path.splitext(full_path)[1].lower() not in valid_extensions:
                continue
            targets.append(full_path.replace('\\', '/'))
        return ";".join(targets)

    def generate_ini(self, program_path):
        ini_content = f"""; Arquivo gerado automaticamente
logToFile={os.path.join(self.logs_dir, 'tds_exec.log').replace('\\', '/')}
showConsoleOutput=true

[user]
INCLUDE_DIR={INCLUDE_DIR.replace('\\', '/')}

[authentication]
action=authentication
server={BUILD_SERVER}
port={BUILD_PORT}
secure=0
build={BUILD_VERSION}
environment={BUILD_ENV}
user={TDS_USER}
psw={TDS_PWD}

[compile]
action=compile
program={self.get_compile_targets(program_path)}
recompile=T
includes=${{INCLUDE_DIR}}
"""
        with open('compile.ini', 'w', encoding='cp1252') as f: f.write(ini_content)
        return 'compile.ini'

    def compile(self):
        global fontes_compilados_qtd
        logging.info("--- PASSO 2: INICIANDO COMPILACAO VIA TDS-CLI ---")
        
        if not os.path.exists(TDS_CLI_PATH):
            logging.error(f"Executável não encontrado: {TDS_CLI_PATH}")
            return False

        ini_file = self.generate_ini(SOURCE_WORKSPACE)
        cmd = [TDS_CLI_PATH, 'cli', ini_file]
        print("\n" + "="*60 + "\n>>> MOTOR DA TOTVS EM EXECUCAO <<<\n" + "="*60)
        
        try:
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, 
                                       cwd=os.getcwd(), text=True, bufsize=1, encoding='latin-1')

            for line in process.stdout:
                if "jsonrpc" not in line and "$totvsserver" not in line and line.strip():
                    print(f"[TDS] {line.strip()}")
                    texto_linha = line.lower()
                    if "compilado" in texto_linha or "successfully" in texto_linha or "compiling" in texto_linha:
                        if ".prw" in texto_linha or ".prx" in texto_linha or ".tlpp" in texto_linha:
                            fontes_compilados_qtd += 1
            process.wait()
            print("="*60 + "\n")
            if process.returncode != 0:
                logging.error(f"ERRO de compilação (Código {process.returncode}).")
                return False
            return True
        except Exception as e:
            logging.error(f"Falha ao executar o compilador: {e}")
            return False

def hot_swap_rpos(env_map):
    logging.info("--- PASSO 3: TROCA QUENTE DE RPOS (RELEASE) ---")
    rpos_to_copy = ["tttm120.rpo", "custom.rpo"]
    target_dirs = set(info['next'] for info in env_map.values())
    
    if not os.path.exists(DIR_PCOMPILA):
        logging.error(f"Pasta de compilacao nao encontrada: {DIR_PCOMPILA}")
        return False
        
    for target in target_dirs:
        target_path = os.path.join(BASE_APO_DIR, target)
        os.makedirs(target_path, exist_ok=True)
        
        for rpo in rpos_to_copy:
            src = os.path.join(DIR_PCOMPILA, rpo)
            dst = os.path.join(target_path, rpo)
            if os.path.exists(src):
                logging.info(f"Distribuindo {rpo} -> {target_path}")
                shutil.copy2(src, dst)
    return True

def update_ini_files(env_map):
    logging.info("--- PASSO 4: ATUALIZACAO DOS APPSERVER.INI (COMENTA E DESCOMENTA) ---")
    for ini_path, info in env_map.items():
        current_dir = info['current']
        next_dir = info['next']
        
        with open(ini_path, 'r', encoding='latin-1') as f:
            lines = f.readlines()
            
        with open(ini_path, 'w', encoding='latin-1') as f:
            for line in lines:
                upper_line = line.upper()
                is_rpo_line = "SOURCEPATH=" in upper_line or "RPOCUSTOM=" in upper_line
                
                if is_rpo_line:
                    stripped_line = line.strip()
                    
                    # 1. Se for o diretorio atual e estiver DESCOMENTADO -> COMENTA
                    if current_dir in upper_line and not stripped_line.startswith("#"):
                        line = "#" + line
                        
                    # 2. Se for o proximo diretorio e estiver COMENTADO -> DESCOMENTA
                    elif next_dir in upper_line and stripped_line.startswith("#"):
                        # Encontra a posicao do primeiro '#' e remove
                        idx = line.find('#')
                        if idx != -1:
                            line = line[:idx] + line[idx+1:]
                            
                f.write(line)
        logging.info(f"Atualizado: {os.path.basename(ini_path)} (Inativou {current_dir}, Ativou {next_dir})")

def validate_rpo_update(env_map):
    logging.info("--- PASSO 5: VALIDACAO ---")
    validation_results = {}
    for ini_path, info in env_map.items():
        expected_dir = info['next']
        is_valid = False
        with open(ini_path, 'r', encoding='latin-1') as f:
            lines = f.readlines()
        
        # Validando as linhas que estao ativas no arquivo (sem #)
        for line in lines[:20]: # Busca nas primeiras linhas
            if not line.strip().startswith("#") and ("SourcePath=" in line or "RPOCustom=" in line):
                if expected_dir in line.upper():
                    is_valid = True
                    break
        validation_results[ini_path] = is_valid
    return validation_results

# --- EXECUÇÃO PRINCIPAL E DASHBOARD SRE ---
if __name__ == "__main__":
    logging.info("=== START SRE PIPELINE - VALECARD ===")
    
    if not update_git_workspace(): sys.exit(1)
        
    env_map = analyze_environments()
    if not env_map:
        logging.error("Nenhum arquivo INI valido encontrado. Abortando.")
        sys.exit(1)
        
    if not prepare_base_rpo(env_map):
        logging.error("Falha ao preparar o RPO base para compilação.")
        sys.exit(1)
        
    compiler = TDSCompiler()
    if not compiler.compile():
        logging.error("A rotina foi abortada devido a erros de compilação.")
        sys.exit(1)
        
    if not hot_swap_rpos(env_map):
        logging.error("Falha na distribuicao dos arquivos RPO.")
        sys.exit(1)
        
    update_ini_files(env_map)
    validacoes = validate_rpo_update(env_map)
    
    # --- DASHBOARD FINAL (RESUMO EXECUTIVO) ---
    print("\n" + "="*70)
    print("                 RESUMO EXECUTIVO DO DEPLOY SRE                 ")
    print("="*70)
    print(f"[+] Git Branch Atualizada : {GIT_BRANCH.upper()}")
    print(f"[+] Total de Fontes Comp. : {fontes_compilados_qtd} (Aprox.)")
    print("-" * 70)
    print(f"{'ARQUIVO INI':<30} | {'INATIVADO (ANTIGO)':<18} | {'ATIVADO (NOVO)':<16} | {'STATUS'}")
    print("-" * 70)
    
    todos_ok = True
    for ini_path, info in env_map.items():
        nome_ini = os.path.basename(ini_path)
        status = "OK [Validado]" if validacoes[ini_path] else "FALHA"
        if not validacoes[ini_path]: todos_ok = False
        print(f"{nome_ini:<30} | {info['current']:<18} | {info['next']:<16} | {status}")
        
    print("="*70)
    if todos_ok:
        logging.info("=== DEPLOY REALIZADO COM SUCESSO. RPOS ATUALIZADOS! ===")
    else:
        logging.error("=== DEPLOY CONCLUIDO, MAS HOUVE FALHA NA VALIDACAO DE ALGUNS INIs ===")