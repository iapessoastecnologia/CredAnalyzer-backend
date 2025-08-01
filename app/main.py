import re
from fastapi import FastAPI, UploadFile, File, HTTPException, Form, Body, Request, Query, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional, Dict, Any
from openai import OpenAI
from .utils import extract_text_from_document
import os
import logging
import json
import io
import tempfile
from pathlib import Path
from dotenv import load_dotenv
from pydantic import BaseModel
import datetime
import tiktoken
import stripe
import firestore

# Importar módulos Firebase
try:
    from app.firebase_service import initialize_firebase, save_report, get_reports_by_date_range, firebase_admin_available
    firebase_available = True
except ImportError:
    firebase_available = False
    logging.warning("Módulo firebase_service não encontrado. Funcionalidades de Firebase não estarão disponíveis.")

# Importar módulos Stripe
try:
    from app.stripe_service import (
        init_stripe, criar_cliente, criar_sessao_checkout, criar_assinatura,
        processar_webhook, listar_cartoes, adicionar_cartao, remover_cartao,
        atualizar_cartao_padrao, consumir_relatorio, obter_historico_pagamentos, criar_pagamento_pix
    )
    stripe_available = True
except ImportError:
    stripe_available = False
    logging.warning("Módulo stripe_service não encontrado. Funcionalidades de Stripe não estarão disponíveis.")

# Carregar variáveis de ambiente do .env
load_dotenv()

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# Configurar CORS para seu frontend (em produção coloque o domínio específico)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Instancia o client OpenAI
client = None
api_key = os.getenv("OPENAI_API_KEY")

try:
    if api_key:
        client = OpenAI(api_key=api_key)
        logger.info("Cliente OpenAI inicializado com sucesso")
    else:
        logger.error("OPENAI_API_KEY não encontrada nas variáveis de ambiente")
        logger.info("Verifique se o arquivo .env existe na raiz do projeto e contém: OPENAI_API_KEY=sua_chave")
except Exception as e:
    logger.warning(f"Não foi possível inicializar o cliente OpenAI: {str(e)}")

def load_prompt_from_file(prompt_file_path: str = "prompt.txt", format: str = "txt") -> str:
    """Carrega o prompt do sistema a partir de um arquivo txt"""
    try:
        # Caminhos possíveis considerando a estrutura: app/ contém os arquivos Python
        current_dir = Path(__file__).parent  # diretório app/
        root_dir = current_dir.parent  # diretório raiz do projeto
        
        possible_paths = [
            current_dir / prompt_file_path,  # app/prompt.txt
            root_dir / prompt_file_path,     # raiz/prompt.txt
            current_dir / "prompts" / prompt_file_path,  # app/prompts/prompt.txt
            root_dir / "prompts" / prompt_file_path,     # raiz/prompts/prompt.txt
        ]
        
        for path in possible_paths:
            if path.exists():
                with open(path, 'r', encoding='utf-8') as f:
                    prompt = f.read().strip()
                    logger.info(f"Prompt carregado de: {path}")
                    return prompt
        
        # Se não encontrou o arquivo, usar um prompt padrão
        logger.warning(f"Arquivo de prompt não encontrado nos caminhos: {[str(p) for p in possible_paths]}")
        return """Você é um analista financeiro especializado em análise de documentos empresariais.

Analise os documentos fornecidos e forneça um relatório detalhado que inclua:

1. **Resumo Executivo**: Principais pontos identificados nos documentos
2. **Análise Financeira**: Situação financeira da empresa baseada nos documentos
3. **Situação Fiscal**: Status fiscal e tributário
4. **Recomendações**: Sugestões e pontos de atenção
5. **Observações**: Qualquer irregularidade ou ponto importante identificado

Seja objetivo, profissional e destaque os pontos mais importantes."""
        
    except Exception as e:
        logger.error(f"Erro ao carregar prompt: {str(e)}")
        return "Você é um analista financeiro. Analise os documentos fornecidos e forneça um relatório detalhado."

# Parâmetros do modelo
MODELO = "gpt-4o-mini"
LIMITE_TOTAL_TOKENS = 128000
LIMITE_COMPLETION = 16384
LIMITE_PROMPT = LIMITE_TOTAL_TOKENS - LIMITE_COMPLETION

def extrair_segmento_do_cnae(texto: str) -> str:
    """
    Extrai o segmento da empresa a partir do CNAE principal encontrado no cartão CNPJ.
    
    Args:
        texto (str): Texto extraído do cartão CNPJ
        
    Returns:
        str: Segmento da empresa ('Varejo', 'Indústria', 'Serviços', 'Tecnologia', 'Saúde', 'Educação' ou 'Outro')
    """
    logger.info("Extraindo segmento a partir do CNAE")
    
    # Padrões para buscar CNAE principal (diferentes formatos possíveis)
    padroes_cnae = [
        # Formato "CNAE principal"
        r"CNAE\s+principal:?\s*(\d+\-\d+\/\d+|\d+\.\d+\-\d+\-\d+|\d+\-\d+|\d+\.\d+)",
        
        # Formato "atividade econômica principal"
        r"atividade\s+econ[ôo]mica\s+principal:?\s*(\d+\-\d+\/\d+|\d+\.\d+\-\d+\-\d+|\d+\-\d+|\d+\.\d+)",
        
        # Formato "CÓDIGO E DESCRIÇÃO DA ATIVIDADE ECONÔMICA PRINCIPAL"
        r"C[ÓO]DIGO\s+E\s+DESCRI[ÇC][ÃA]O\s+DA\s+ATIVIDADE\s+ECON[ÔO]MICA\s+PRINCIPAL[:\s]*(\d+\-\d+\/\d+|\d+\.\d+\-\d+\-\d+|\d+\-\d+|\d+\.\d+)",
        
        # Formato simplificado que busca apenas números em formato de CNAE após "principal"
        r"principal\s*[:\-]?\s*(\d+\-\d+\/\d+|\d+\.\d+\-\d+\-\d+|\d+\-\d+|\d+\.\d+)"
    ]
    
    # Buscar CNAE principal no texto usando os padrões definidos
    for padrao in padroes_cnae:
        match_cnae = re.search(padrao, texto, re.IGNORECASE)
        if match_cnae:
            cnae = match_cnae.group(1)
            logger.info(f"CNAE principal encontrado: {cnae}")
            
            # Limpar o CNAE para ter apenas os primeiros dígitos (divisão)
            cnae_limpo = re.sub(r"[^\d]", "", cnae)[:2]  # Pegar apenas os dois primeiros dígitos
            
            try:
                cnae_num = int(cnae_limpo)
                
                # Classificar o CNAE de acordo com os segmentos
                # Baseado na Classificação Nacional de Atividades Econômicas (IBGE)
                
                # Varejo: comércio varejista e atacadista (divisões 45 a 47)
                if 45 <= cnae_num <= 47:
                    return "Varejo"
                    
                # Indústria: indústrias extrativas e de transformação (divisões 05 a 33)
                elif 5 <= cnae_num <= 33:
                    return "Indústria"
                    
                # Tecnologia: Informação e comunicação (divisões 58 a 63) e Pesquisa científica (divisão 72)
                elif (58 <= cnae_num <= 63) or cnae_num == 72:
                    return "Tecnologia"
                    
                # Saúde: Atividades de atenção à saúde humana (divisões 86 a 88)
                elif 86 <= cnae_num <= 88:
                    return "Saúde"
                    
                # Educação: Educação (divisão 85)
                elif cnae_num == 85:
                    return "Educação"
                    
                # Serviços: Todos os outros CNAEs
                else:
                    return "Serviços"
                    
            except ValueError:
                logger.warning(f"Não foi possível converter o CNAE '{cnae_limpo}' para número")
                continue  # Tenta o próximo padrão se a conversão falhar
    
    logger.warning("Não foi encontrado CNAE principal no texto")
    return "Outro"

async def analyze_with_openai(combined_text: str) -> tuple:
    """Envia o texto extraído para análise da OpenAI e retorna a análise e o uso de tokens"""
    if not client:
        raise HTTPException(
            status_code=500,
            detail="Cliente OpenAI não está configurado. Verifique a OPENAI_API_KEY."
        )

    try:
        # Carrega o prompt do arquivo
        system_prompt = load_prompt_from_file()

        # Parte fixa do prompt do usuário
        prompt_fixo = (
            "Analise o seguinte conteúdo dos documentos empresariais:\n\n"
        )
        prompt_final = (
            "\n\nForneça uma análise completa seguindo a estrutura solicitada. \n"
            "Note que pode haver múltiplos documentos para cada categoria "
            "(ex: múltiplos arquivos de Faturamento Fiscal ou SPC/Serasa). "
            "Considere todos os documentos em sua análise, mesmo que sejam da mesma categoria."
        )

        # Inicializa o tokenizador
        encoding = tiktoken.encoding_for_model(MODELO)

        # Calcula tokens fixos (system + prompt + instruções)
        system_tokens = len(encoding.encode(system_prompt))
        fixed_tokens = len(encoding.encode(prompt_fixo + prompt_final))

        # Quanto sobra para os documentos
        tokens_disponiveis_para_docs = LIMITE_PROMPT - system_tokens - fixed_tokens

        # Codifica o texto dos documentos
        doc_tokens = encoding.encode(combined_text)

        if len(doc_tokens) > tokens_disponiveis_para_docs:
            logger.warning(
                f"Texto muito grande ({len(doc_tokens)} tokens). "
                f"Truncando para {tokens_disponiveis_para_docs} tokens."
            )
            doc_tokens = doc_tokens[:tokens_disponiveis_para_docs]
            combined_text = encoding.decode(doc_tokens)
            combined_text += "\n\n[TEXTO TRUNCADO AUTOMATICAMENTE]"

        # Monta o prompt final
        user_prompt = f"{prompt_fixo}{combined_text}{prompt_final}"
        
        # Imprime o texto combinado final após todas as transformações
        print("\n===== TEXTO COMBINADO FINAL APÓS TRANSFORMAÇÕES =====")
        print(f"Tamanho total: {len(combined_text)} caracteres")
        print("Primeiros 500 caracteres:")
        print(combined_text[:500] + "..." if len(combined_text) > 500 else combined_text)
        print("Últimos 500 caracteres:")
        print("..." + combined_text[-500:] if len(combined_text) > 500 else combined_text)
        print("============================================\n")
        
        # Imprime o prompt do sistema e uma parte do prompt do usuário para visualização
        print("\n===== PROMPT DO SISTEMA =====")
        print(system_prompt[:500] + "..." if len(system_prompt) > 500 else system_prompt)
        print("\n===== PARTE DO PROMPT DO USUÁRIO =====")
        print(user_prompt[:500] + "...")  # Mostrar apenas os primeiros 500 caracteres
        print("=================================\n")

        logger.info("Enviando texto para análise da OpenAI...")

        # Envia para a API
        response = client.chat.completions.create(
            model=MODELO,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            max_tokens=LIMITE_COMPLETION,
            temperature=0.4
        )

        # Extrai resultado
        analysis = response.choices[0].message.content
        token_usage = {
            "prompt_tokens": response.usage.prompt_tokens,
            "completion_tokens": response.usage.completion_tokens,
            "total_tokens": response.usage.total_tokens
        }

        logger.info(f"Análise concluída. Tokens utilizados: {token_usage}")
        
        # Verificar se a resposta está em formato markdown e destacar isso
        print("\n===== VERIFICAÇÃO DE FORMATO MARKDOWN NA RESPOSTA =====")
        markdown_indicators = [
            "# ", "## ", "### ", "#### ", "##### ", "- ", "* ", "1. ", "> ", "```", "---",
            "**", "_", "[", "](", "|", "+-"
        ]
        has_markdown = any(indicator in analysis for indicator in markdown_indicators)
        print(f"A resposta contém formatação markdown: {'Sim' if has_markdown else 'Não'}")
        
        if has_markdown:
            print("\n===== ELEMENTOS MARKDOWN DETECTADOS =====")
            for indicator in markdown_indicators:
                if indicator in analysis:
                    print(f"- {indicator}")
        
        # Mostrar parte da análise recebida
        print("\n===== PARTE DA ANÁLISE RECEBIDA =====")
        print(analysis[:1000] + "..." if len(analysis) > 1000 else analysis)
        print("====================================\n")

        return analysis, token_usage

    except Exception as e:
        logger.error(f"Erro ao chamar OpenAI: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Erro ao processar análise: {str(e)}")

@app.post("/analyze/")
async def analyze(
    files: List[UploadFile] = File(...),
    planning_data: Optional[str] = Form(None),
    user_id: Optional[str] = Form(None)
):
    logger.info(f"Recebido {len(files)} arquivos para análise")
    
    if not files:
        raise HTTPException(status_code=400, detail="Nenhum arquivo enviado.")

    # Verificar se o usuário tem relatórios disponíveis
    if user_id and stripe_available:
        resultado = consumir_relatorio(user_id)
        if not resultado.get("success"):
            raise HTTPException(
                status_code=402, 
                detail="Não há relatórios disponíveis. Adquira um plano para continuar."
            )
        logger.info(f"Usuário {user_id} tem {resultado.get('reports_left')} relatórios restantes")
    
    combined_text = ""
    processed_files = []
    registrato_files = []  # Armazenar os arquivos Registrato para processamento posterior
    cartao_cnpj_text = ""
    
    # Processar dados de planejamento, se fornecidos
    if planning_data:
        try:
            planning_json = json.loads(planning_data)
            logger.info(f"Dados de planejamento recebidos: {planning_json}")
            print("\n===== DADOS DE PLANEJAMENTO RECEBIDOS =====")
            print(json.dumps(planning_json, indent=2, ensure_ascii=False))
            print("===========================================\n")
            
            combined_text += "=== DADOS DE PLANEJAMENTO ===\n"
            
            # Remover recepção do segmento - será extraído do cartão CNPJ
            
            # Adicionar objetivo
            if planning_json.get("objective"):
                objective = planning_json["objective"]
                if objective == "Outro" and planning_json.get("otherObjective"):
                    objective = planning_json["otherObjective"]
                combined_text += f"Objetivo do Crédito: {objective}\n"
            
            # Adicionar valor do crédito
            if planning_json.get("creditAmount"):
                combined_text += f"Valor do Crédito Buscado: R$ {planning_json['creditAmount']}\n"
            
            # Adicionar tempo na empresa
            if planning_json.get("timeInCompany"):
                combined_text += f"Tempo na Empresa: {planning_json['timeInCompany']} anos\n"
                
            # Adicionar carência solicitada
            if planning_json.get("gracePeriod"):
                combined_text += f"Carência Solicitada: {planning_json['gracePeriod']} meses\n"
            
            # Adicionar garantias
            if planning_json.get("collaterals") and isinstance(planning_json["collaterals"], list):
                combined_text += "Garantias:\n"
                for idx, collateral in enumerate(planning_json["collaterals"]):
                    if isinstance(collateral, dict):
                        tipo = collateral.get("type", "Não especificado")
                        valor = collateral.get("value", 0)
                        combined_text += f"  - Garantia {idx+1}: {tipo}, Valor: R$ {valor}\n"
                
            combined_text += "\n\n"
        except json.JSONDecodeError as e:
            logger.error(f"Erro ao decodificar dados de planejamento: {str(e)}")
            # Continuar mesmo com erro nos dados de planejamento
    
    # Primeira etapa: Extrair texto de todos os arquivos
    print("\n===== INICIANDO PROCESSAMENTO DE ARQUIVOS =====")
    print(f"Total de arquivos recebidos: {len(files)}")
    
    for i, file in enumerate(files):
        logger.info(f"Processando arquivo {i+1}: {file.filename}, tipo: {file.content_type}")
        print(f"\nProcessando arquivo {i+1}/{len(files)}: {file.filename} ({file.content_type})")
        
        # Verificar se o tipo de arquivo é suportado
        content_type = file.content_type
        supported_types = ["application/pdf", "image/jpeg", "image/png", 
                          "application/msword", 
                          "application/vnd.openxmlformats-officedocument.wordprocessingml.document"]
        
        if content_type not in supported_types:
            logger.error(f"Tipo de arquivo não suportado: {content_type}")
            raise HTTPException(
                status_code=400, 
                detail=f"Arquivo {file.filename} não é suportado. Formatos aceitos: PDF, JPEG, PNG, DOC, DOCX."
            )
            
        # Identificar categoria do arquivo para uma melhor organização no texto
        category = None
        filename = file.filename.lower()
        
        print(f"Identificando categoria para arquivo: {file.filename}")
        
        # Verificar se é um cartão CNPJ para extrair o segmento
        if 'cnpj' in filename or 'cartao' in filename:
            category = 'Cartão CNPJ'
            print(f"  -> Categoria identificada: {category} (contém 'cnpj' ou 'cartao')")
            
            # Extrair texto do documento para CNPJ
            try:
                logger.info(f"Iniciando extração de texto para {file.filename}")
                text = await extract_text_from_document(file)
                
                if not text or not text.strip():
                    logger.warning(f"Arquivo {file.filename} está vazio ou não pôde ser lido.")
                    processed_files.append({
                        "filename": file.filename,
                        "status": "vazio",
                        "text_length": 0
                    })
                    continue
                
                cartao_cnpj_text += text  # Armazenar texto do cartão CNPJ
                combined_text += f"\n=== DOCUMENTO ({category}): {file.filename} ===\n"
                combined_text += text + "\n\n"
                
                processed_files.append({
                    "filename": file.filename,
                    "status": "processado",
                    "text_length": len(text),
                    "category": category
                })
                
                logger.info(f"Arquivo {file.filename} processado com sucesso. Texto extraído: {len(text)} caracteres")
                print(f"Arquivo processado com sucesso. Categoria identificada: {category}")
                print(f"Total de caracteres extraídos: {len(text)}")
            except Exception as e:
                logger.error(f"Erro ao processar {file.filename}: {str(e)}")
                raise HTTPException(
                    status_code=400, 
                    detail=f"Erro ao processar {file.filename}: {str(e)}"
                )
        elif 'registrato' in filename:
            # Para arquivos Registrato, armazenar para processamento posterior com DocLing
            category = 'Registro'
            print(f"  -> Categoria identificada: {category} (contém 'registrato')")
            logger.info(f"Registrato identificado: {file.filename}. Será processado com DocLing posteriormente.")
            
            # Adicionar à lista de registratos para processar depois
            registrato_files.append({
                "file": file,
                "filename": file.filename,
                "index": i+1
            })
            
            # Adicionar um placeholder temporário
            combined_text += f"\n=== DOCUMENTO ({category}): {file.filename} ===\n"
            combined_text += f"[REGISTRATO - SERÁ PROCESSADO COM CAMELOT]\n\n"
            
            processed_files.append({
                "filename": file.filename,
                "status": "para_processamento",
                "category": category
            })
        else:
            # Para outros tipos de arquivos, processar normalmente
            if 'imposto' in filename or 'irpf' in filename:
                category = 'Imposto de Renda'
                print(f"  -> Categoria identificada: {category} (contém 'imposto' ou 'irpf')")
            elif 'registro' in filename or 'contrato' in filename:
                category = 'Registro'
                print(f"  -> Categoria identificada: {category} (contém 'registro' ou 'contrato')")
            elif 'fiscal' in filename:
                category = 'Situação Fiscal'
                print(f"  -> Categoria identificada: {category} (contém 'fiscal')")
            elif 'faturamento' in filename:
                if 'gerencial' in filename:
                    category = 'Faturamento Gerencial'
                    print(f"  -> Categoria identificada: {category} (contém 'faturamento' e 'gerencial')")
                else:
                    category = 'Faturamento Fiscal'
                    print(f"  -> Categoria identificada: {category} (contém 'faturamento')")
            elif 'spc' in filename or 'serasa' in filename:
                category = 'SPC e Serasa'
                print(f"  -> Categoria identificada: {category} (contém 'spc' ou 'serasa')")
            elif 'demonstrativo' in filename or 'extrato' in filename:
                category = 'Demonstrativo'
                print(f"  -> Categoria identificada: {category} (contém 'demonstrativo' ou 'extrato')")
            else:
                category = 'Documento Adicional'
                print(f"  -> Categoria identificada: {category} (categoria padrão)")
                
            # Extrair texto do documento
            try:
                logger.info(f"Iniciando extração de texto para {file.filename}")
                text = await extract_text_from_document(file)
                
                if not text or not text.strip():
                    logger.warning(f"Arquivo {file.filename} está vazio ou não pôde ser lido.")
                    processed_files.append({
                        "filename": file.filename,
                        "status": "vazio",
                        "text_length": 0
                    })
                    continue
                
                combined_text += f"\n=== DOCUMENTO ({category}): {file.filename} ===\n"
                combined_text += text + "\n\n"
                
                processed_files.append({
                    "filename": file.filename,
                    "status": "processado",
                    "text_length": len(text),
                    "category": category
                })
                
                logger.info(f"Arquivo {file.filename} processado com sucesso. Texto extraído: {len(text)} caracteres")
                print(f"Arquivo processado com sucesso. Categoria identificada: {category}")
                print(f"Total de caracteres extraídos: {len(text)}")
                
            except Exception as e:
                logger.error(f"Erro ao processar {file.filename}: {str(e)}")
                raise HTTPException(
                    status_code=400, 
                    detail=f"Erro ao processar {file.filename}: {str(e)}"
                )
    
    if not combined_text.strip():
        raise HTTPException(
            status_code=400,
            detail="Nenhum texto foi extraído dos arquivos enviados."
        )
    
    # Extrair o segmento a partir do texto do cartão CNPJ
    segment = "Outro"
    if cartao_cnpj_text:
        segment = extrair_segmento_do_cnae(cartao_cnpj_text)
        logger.info(f"Segmento extraído do CNAE: {segment}")
        print(f"\n===== SEGMENTO EXTRAÍDO DO CNAE: {segment} =====")
        
        # Adicionar o segmento identificado aos dados de planejamento para o contexto da análise
        combined_text = combined_text.replace("=== DADOS DE PLANEJAMENTO ===\n", 
                                             f"=== DADOS DE PLANEJAMENTO ===\nSegmento da Empresa: {segment}\n")
    else:
        logger.warning("Cartão CNPJ não encontrado. Segmento não pôde ser extraído.")
        print("\n===== CARTÃO CNPJ NÃO ENCONTRADO. SEGMENTO NÃO EXTRAÍDO =====")
    
    logger.info(f"Extração concluída. Total de texto: {len(combined_text)} caracteres")
    print(f"\n===== EXTRAÇÃO CONCLUÍDA =====")
    print(f"Total de texto combinado: {len(combined_text)} caracteres")
    print(f"Total de arquivos processados: {len([f for f in processed_files if f['status'] == 'processado'])}")
    print(f"Total de registratos para processar: {len(registrato_files)}")
    print("===============================\n")
    
    # Processar os registratos SCR com camelot
    print("\n===== PROCESSANDO REGISTRATOS SCR COM CAMELOT =====")
    
    try:
        print("✅ Sistema de processamento SCR inicializado")
        
        # Lista para armazenar os markdowns processados
        registratos_processados = []
        
        # Processar cada arquivo registrato
        for registrato in registrato_files:
            file = registrato["file"]
            filename = registrato["filename"]
            
            print(f"\nProcessando registrato: {filename}")
            
            try:
                # Ler o conteúdo do arquivo diretamente
                await file.seek(0)
                file_content = await file.read()
                
                print(f"Arquivo lido em memória, tamanho: {len(file_content)} bytes")
                
                # Tentar primeiro o processamento estruturado de SCR
                try:
                    from app.utils import extract_scr_data_from_pdf
                    
                    print(f"Tentando processamento estruturado de SCR para: {filename}")
                    scr_data = extract_scr_data_from_pdf(file_content, filename)
                    
                    # Formatar os dados para markdown estruturado
                    processed_text = f"## Dados SCR: {filename}\n\n"
                    
                    if scr_data.get('erro'):
                        processed_text += f"**ERRO**: {scr_data['erro']}\n\n"
                except ImportError as e:
                    print(f"⚠️ Erro ao importar função de processamento SCR: {str(e)}")
                    processed_text = f"## Erro no Processamento SCR: {filename}\n\n**ERRO**: Não foi possível processar o arquivo SCR. Dependências não disponíveis.\n\n"
                except Exception as e:
                    print(f"⚠️ Erro no processamento SCR: {str(e)}")
                    processed_text = f"## Erro no Processamento SCR: {filename}\n\n**ERRO**: {str(e)}\n\n"
                else:
                    processed_text += "### Informações da Empresa\n\n"
                    processed_text += f"- **Nome**: {scr_data['empresa_nome']}\n"
                    processed_text += f"- **CNPJ**: {scr_data['empresa_cnpj']}\n\n"
                    
                    processed_text += "### Dívidas Extraídas\n\n"
                    processed_text += f"- **Dívida em dia**: R$ {scr_data['divida_em_dia']:.2f}\n"
                    processed_text += f"- **Dívida vencida**: R$ {scr_data['divida_vencida']:.2f}\n"
                    processed_text += f"- **Total de dívidas**: R$ {scr_data['total_dividas']:.2f}\n\n"
                    
                    # Adicionar informação sobre a planilha Excel
                    if scr_data.get('planilha_gerada'):
                        processed_text += f"### Arquivo Excel\n\n"
                        processed_text += f"- **Planilha gerada**: {scr_data['planilha_gerada']}\n\n"
                
                # Adicionar informação sobre a extração direta
                processed_text += "*Nota: Estes valores foram extraídos diretamente das posições [2,1] (dívida em dia) e [2,2] (dívida vencida) do arquivo SCR e convertidos para formato Excel (.xlsx).*\n\n"
                
                print(f"✅ Processamento estruturado de SCR concluído: {len(processed_text)} caracteres")
                if not scr_data.get('erro'):
                    print(f"Empresa: {scr_data['empresa_nome']} ({scr_data['empresa_cnpj']})")
                    print(f"Dívida em dia: R$ {scr_data['divida_em_dia']:.2f}")
                    print(f"Dívida vencida: R$ {scr_data['divida_vencida']:.2f}")
                    print(f"Total: R$ {scr_data['total_dividas']:.2f}")
                
                # Mostrar informação sobre a planilha gerada
                if scr_data.get('planilha_gerada'):
                    print(f"📊 Planilha Excel: {scr_data['planilha_gerada']}")
                
                # Armazenar o resultado processado
                registratos_processados.append({
                    "filename": filename,
                    "markdown": processed_text
                })
                
                # Substituir o placeholder pelo texto processado no texto combinado
                placeholder = f"\n=== DOCUMENTO (Registro): {filename} ===\n[REGISTRATO - SERÁ PROCESSADO COM CAMELOT]\n\n"
                replacement = f"\n=== DOCUMENTO (Registro): {filename} ===\n{processed_text}\n\n"
                combined_text = combined_text.replace(placeholder, replacement)
                
                print(f"✅ Registrato processado: {filename}")
                
            except Exception as e:
                print(f"⚠️ Erro ao processar registrato {filename}: {str(e)}")
                logger.error(f"Erro ao processar registrato {filename}: {str(e)}")
                
                # Adicionar mensagem de erro ao texto combinado
                placeholder = f"\n=== DOCUMENTO (Registro): {filename} ===\n[REGISTRATO - SERÁ PROCESSADO COM CAMELOT]\n\n"
                replacement = f"\n=== DOCUMENTO (Registro): {filename} ===\n[ERRO AO PROCESSAR REGISTRATO: {str(e)}]\n\n"
                combined_text = combined_text.replace(placeholder, replacement)
        
        print(f"\nTotal de {len(registratos_processados)} registratos processados")
        
        # Exibir o conteúdo completo dos registratos processados
        if registratos_processados:
            print("\n\n========================================================")
            print("     CONTEÚDO COMPLETO DOS REGISTRATOS PROCESSADOS      ")
            print("========================================================\n")
            
            for idx, reg in enumerate(registratos_processados):
                print(f"[REGISTRATO {idx+1}: {reg['filename']}]")
                print("TEXTO APÓS PROCESSAMENTO MARKDOWN:")
                print("----------------------------------------")
                print(reg['markdown'])
                print("----------------------------------------\n")
        
    except Exception as e:
        print(f"⚠️ Erro no processamento de registratos: {str(e)}")
        logger.error(f"Erro no processamento de registratos: {str(e)}")
        
        # Adicionar mensagem de erro para todos os registratos
        for registrato in registrato_files:
            filename = registrato["filename"]
            placeholder = f"\n=== DOCUMENTO (Registro): {filename} ===\n[REGISTRATO - SERÁ PROCESSADO COM CAMELOT]\n\n"
            replacement = f"\n=== DOCUMENTO (Registro): {filename} ===\n[ERRO: {str(e)}]\n\n"
            combined_text = combined_text.replace(placeholder, replacement)
    
    # Atualizar os dados de planejamento para incluir o segmento extraído
    if planning_data:
        try:
            planning_json = json.loads(planning_data)
            planning_json["segment"] = segment
            planning_data = json.dumps(planning_json)
        except json.JSONDecodeError as e:
            logger.error(f"Erro ao atualizar dados de planejamento: {str(e)}")
    else:
        planning_data = json.dumps({"segment": segment})
    
    # Segunda etapa: Enviar para OpenAI para análise
    try:
        print("\n===== ENVIANDO PARA ANÁLISE DA OPENAI =====")
        print(f"Modelo utilizado: {MODELO}")
        print(f"Tamanho do texto a ser analisado: {len(combined_text)} caracteres")
        
        analysis, token_usage = await analyze_with_openai(combined_text)
        
        print("\n===== ANÁLISE CONCLUÍDA =====")
        print(f"Tokens do prompt: {token_usage['prompt_tokens']}")
        print(f"Tokens da resposta: {token_usage['completion_tokens']}")
        print(f"Total de tokens: {token_usage['total_tokens']}")
        print("=============================\n")
        
        # Agrupar arquivos processados por categoria
        files_by_category = {}
        for file in processed_files:
            if "category" in file:
                category = file["category"]
                if category not in files_by_category:
                    files_by_category[category] = []
                files_by_category[category].append(file)
        
        return {
            "success": True,
            "analysis": analysis,
            "processed_files": processed_files,
            "files_by_category": files_by_category,
            "total_text_length": len(combined_text),
            "files_processed": len([f for f in processed_files if f['status'] == 'processado']),
            "token_usage": token_usage,
            "detected_segment": segment  # Retornar o segmento extraído
        }
        
    except HTTPException:
        # Re-raise HTTPExceptions (já tratadas)
        raise
    except Exception as e:
        logger.error(f"Erro inesperado: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Erro interno do servidor: {str(e)}"
        )

@app.get("/health")
async def health_check():
    """Endpoint para verificar se a API está funcionando"""
    api_key_status = "configurada" if os.getenv("OPENAI_API_KEY") else "não configurada"
    
    return {
        "status": "healthy",
        "openai_configured": client is not None,
        "api_key_status": api_key_status,
        "env_file_path": Path(__file__).parent.parent / ".env",
        "current_working_directory": os.getcwd(),
        "message": "API funcionando corretamente"
    }

# Nova classe para o modelo de dados de relatório
class ReportData(BaseModel):
    user_id: str
    user_name: str
    planning_data: dict
    report_content: str
    
@app.post("/save_report/")
async def save_report_endpoint(
    report_data: str = Form(...),
    files: Optional[List[UploadFile]] = File(None)
):
    if not firebase_available:
        raise HTTPException(status_code=501, detail="Firebase não está disponível")
    
    if not firebase_admin_available:
        raise HTTPException(status_code=501, detail="Módulo firebase_admin não está disponível. Instale-o com: pip install firebase-admin")
    
    try:
        # Inicializar Firebase se necessário
        try:
            import firebase_admin
            if not firebase_admin._apps:
                success = initialize_firebase()
                if not success:
                    raise HTTPException(status_code=500, detail="Não foi possível inicializar o Firebase")
        except (ImportError, NameError) as e:
            raise HTTPException(status_code=500, detail=f"Erro ao acessar firebase_admin: {str(e)}")
        
        # Converter string JSON para dicionário
        data = json.loads(report_data)
        
        # Extrair campos obrigatórios
        user_id = data.get("user_id")
        user_name = data.get("user_name")
        planning_data = data.get("planning_data", {})
        report_content = data.get("report_content")
        
        if not user_id or not user_name or not report_content:
            raise HTTPException(status_code=400, detail="Dados insuficientes para salvar o relatório")
        
        # Checar se o plano foi registrado
        if stripe_available:
            db = get_firestore_db()
            user_doc = db.collection('usuarios').document(user_id).get()
            
            if user_doc.exists:
                user_data = user_doc.to_dict()
                subscription = user_data.get('subscription', {})
                
                if subscription:
                    # Incluir informações do plano nos metadados do relatório
                    planning_data["planoAssinatura"] = {
                        "nome": subscription.get('planName', 'Desconhecido'),
                        "relatoriosRestantes": subscription.get('reportsLeft', 0),
                        "renovacaoAutomatica": subscription.get('autoRenew', False)
                    }
            else:
                logger.warning(f"Usuário {user_id} não tem plano registrado")
        
        # Processar arquivos, se houver
        analysis_files = {}
        
        if files:
            for file in files:
                try:
                    # Exemplo: Identificar tipo de arquivo pelo campo filename
                    filename = file.filename.lower()
                    
                    # Mapeamento simplificado baseado no nome do arquivo
                    category = None
                    if 'imposto' in filename or 'irpf' in filename:
                        category = 'incomeTax'
                    elif 'registro' in filename or 'contrato' in filename:
                        category = 'registration'
                    elif 'fiscal' in filename:
                        category = 'taxStatus'
                    elif 'faturamento' in filename:
                        if 'gerencial' in filename:
                            category = 'managementBilling'
                        else:
                            category = 'taxBilling'
                    elif 'spc' in filename or 'serasa' in filename:
                        category = 'spcSerasa'
                    elif 'demonstrativo' in filename or 'extrato' in filename:
                        category = 'statement'
                    else:
                        # Usar índice para arquivos não identificados
                        category = f'document_{len(analysis_files)}'
                    
                    # Adicionar à lista de arquivos dessa categoria
                    if category not in analysis_files:
                        analysis_files[category] = []
                    
                    analysis_files[category].append(file)
                        
                except Exception as e:
                    logger.error(f"Erro ao processar arquivo: {str(e)}")
        
        # Salvar no Firebase
        result = save_report(
            user_id=user_id,
            user_name=user_name,
            planning_data=planning_data,
            analysis_files=analysis_files, 
            report_content=report_content
        )
        
        if not result.get("success"):
            raise HTTPException(
                status_code=500, 
                detail=f"Erro ao salvar relatório: {result.get('error', 'Erro desconhecido')}"
            )
        
        return {
            "success": True,
            "message": "Relatório salvo com sucesso",
            "report_id": result.get("report_id")
        }
        
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Dados de relatório inválidos. Formato JSON esperado.")
    except Exception as e:
        logger.error(f"Erro ao salvar relatório: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Erro ao salvar relatório: {str(e)}")

@app.get("/firebase_status/")
async def firebase_status():
    """Verifica se a integração com Firebase está disponível e configurada"""
    if not firebase_available:
        return {"available": False, "reason": "Módulo firebase_service não encontrado"}
        
    if not firebase_admin_available:
        return {"available": False, "reason": "Módulo firebase_admin não está disponível. Instale-o com: pip install firebase-admin"}
    
    try:
        # Verificar se o módulo firebase_admin está inicializado
        import firebase_admin
        is_initialized = initialize_firebase()
        
        return {
            "available": True,
            "initialized": is_initialized,
            "message": "Firebase configurado e pronto para uso" if is_initialized else "Firebase não inicializado corretamente"
        }
    except Exception as e:
        return {
            "available": False,
            "reason": f"Erro ao verificar status do Firebase: {str(e)}"
        }

# Inicializar Firebase e Stripe
@app.on_event("startup")
async def startup_event():
    """Evento executado na inicialização da aplicação"""
    # Inicializar Firebase
    if firebase_available:
        try:
            initialize_firebase()
        except Exception as e:
            logger.error(f"Erro ao inicializar Firebase no startup: {str(e)}")

    # Inicializar Stripe
    if stripe_available:
        try:
            init_stripe()
        except Exception as e:
            logger.error(f"Erro ao inicializar Stripe no startup: {str(e)}")

class DateRange(BaseModel):
    start_date: Optional[datetime.date] = None
    end_date: Optional[datetime.date] = None
    user_id: Optional[str] = None

@app.get("/reports/")
async def get_reports(
    start_date: Optional[str] = Query(None, description="Data inicial no formato YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="Data final no formato YYYY-MM-DD"),
    user_id: Optional[str] = Query(None, description="ID do usuário (opcional)")
):
    """
    Retorna os relatórios disponíveis no intervalo de datas especificado.
    Se nenhuma data for especificada, retorna os relatórios do dia atual.
    """
    if not firebase_available:
        raise HTTPException(status_code=501, detail="Funcionalidade do Firebase não disponível")
        
    if not firebase_admin_available:
        raise HTTPException(status_code=501, detail="Módulo firebase_admin não está disponível. Instale-o com: pip install firebase-admin")
    
    # Inicializar Firebase se necessário
    try:
        import firebase_admin
        if not firebase_admin._apps:
            if not initialize_firebase():
                raise HTTPException(status_code=500, detail="Falha ao inicializar Firebase")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao acessar firebase_admin: {str(e)}")
    
    # Converter strings de data para objetos date
    start_date_obj = None
    end_date_obj = None
    
    try:
        if start_date:
            start_date_obj = datetime.date.fromisoformat(start_date)
        if end_date:
            end_date_obj = datetime.date.fromisoformat(end_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Formato de data inválido. Use YYYY-MM-DD")
    
    # Buscar relatórios
    result = get_reports_by_date_range(user_id, start_date_obj, end_date_obj)
    
    if not result["success"]:
        # Se houve erro, retorna o erro como HTTP 500
        raise HTTPException(status_code=500, detail=result.get("error", "Erro desconhecido ao buscar relatórios"))
    
    # Retornar os dados
    return result

# Modelos para API Stripe
class UserData(BaseModel):
    user_id: str
    email: str
    nome: str

class PagamentoRequest(BaseModel):
    user_id: str
    plano_id: str

class PixPagamentoRequest(BaseModel):
    user_id: str
    plano_id: str
    telefone: Optional[str] = None

class CartaoRequest(BaseModel):
    customer_id: str
    payment_method_id: str
    set_default: bool = False

class PagamentoData(BaseModel):
    user_id: str
    payment_id: str
    payment_method: str
    amount: float
    plan_id: str
    plan_name: str
    telefone: Optional[str] = None
    auto_renew: bool = False
    reports_left: int
    creditos_plano: int  # Novo campo para armazenar os créditos fixos do plano
    start_date: datetime.datetime
    end_date: Optional[datetime.datetime] = None

# Endpoints Stripe
@app.post("/stripe/cliente/")
async def criar_cliente_endpoint(user_data: UserData):
    """Cria um cliente no Stripe"""
    if not stripe_available:
        raise HTTPException(status_code=501, detail="Integração com Stripe não disponível")

    customer_id = criar_cliente(user_data.user_id, user_data.email, user_data.nome)
    if not customer_id:
        raise HTTPException(status_code=500, detail="Erro ao criar cliente no Stripe")

    return {"success": True, "customer_id": customer_id}

@app.post("/stripe/checkout/pagamento/")
async def checkout_pagamento(pagamento: PagamentoRequest):
    """Cria uma sessão de checkout para pagamento único"""
    if not stripe_available:
        raise HTTPException(status_code=501, detail="Integração com Stripe não disponível")

    resultado = criar_sessao_checkout(pagamento.user_id, pagamento.plano_id)
    if not resultado.get("success"):
        raise HTTPException(status_code=500, detail=resultado.get("error", "Erro ao criar sessão de checkout"))

    return resultado

@app.post("/stripe/checkout/assinatura/")
async def checkout_assinatura(pagamento: PagamentoRequest):
    """Cria uma sessão de checkout para assinatura recorrente"""
    if not stripe_available:
        raise HTTPException(status_code=503, detail="Serviço Stripe não está disponível")
    
    resultado = criar_assinatura(pagamento.user_id, pagamento.plano_id)
    
    if resultado.get("success"):
        return resultado
    else:
        raise HTTPException(status_code=400, detail=resultado.get("error", "Erro ao criar assinatura"))

@app.post("/stripe/webhook/")
async def webhook(request: Request, stripe_signature: Optional[str] = Header(None)):
    """Recebe webhook do Stripe"""
    if not stripe_available:
        raise HTTPException(status_code=503, detail="Serviço Stripe não está disponível")
    
    payload = await request.body()
    resultado = processar_webhook(payload, stripe_signature)
    
    if resultado.get("success"):
        return resultado
    else:
        raise HTTPException(status_code=400, detail=resultado.get("error", "Erro ao processar webhook"))

@app.get("/stripe/cartoes/{customer_id}")
async def listar_cartoes_endpoint(customer_id: str):
    """Lista os cartões de um cliente"""
    if not stripe_available:
        raise HTTPException(status_code=501, detail="Integração com Stripe não disponível")

    resultado = listar_cartoes(customer_id)
    if not resultado.get("success"):
        raise HTTPException(status_code=500, detail=resultado.get("error", "Erro ao listar cartões"))

    return resultado

@app.post("/stripe/cartoes/")
async def adicionar_cartao_endpoint(cartao: CartaoRequest):
    """Adiciona um cartão ao cliente"""
    if not stripe_available:
        raise HTTPException(status_code=501, detail="Integração com Stripe não disponível")

    resultado = adicionar_cartao(cartao.customer_id, cartao.payment_method_id, cartao.set_default)
    if not resultado.get("success"):
        raise HTTPException(status_code=500, detail=resultado.get("error", "Erro ao adicionar cartão"))

    return resultado

@app.delete("/stripe/cartoes/{customer_id}/{payment_method_id}")
async def remover_cartao_endpoint(customer_id: str, payment_method_id: str):
    """Remove um cartão do cliente"""
    if not stripe_available:
        raise HTTPException(status_code=501, detail="Integração com Stripe não disponível")

    resultado = remover_cartao(customer_id, payment_method_id)
    if not resultado.get("success"):
        raise HTTPException(status_code=500, detail=resultado.get("error", "Erro ao remover cartão"))

    return resultado

@app.put("/stripe/cartoes/{customer_id}/{payment_method_id}/padrao")
async def atualizar_cartao_padrao_endpoint(customer_id: str, payment_method_id: str):
    """Define um cartão como padrão"""
    if not stripe_available:
        raise HTTPException(status_code=501, detail="Integração com Stripe não disponível")

    resultado = atualizar_cartao_padrao(customer_id, payment_method_id)
    if not resultado.get("success"):
        raise HTTPException(status_code=500, detail=resultado.get("error", "Erro ao atualizar cartão padrão"))

    return resultado

@app.post("/stripe/consumir_relatorio/{user_id}")
async def consumir_relatorio_endpoint(user_id: str):
    """Consome um relatório do plano do usuário"""
    if not stripe_available:
        raise HTTPException(status_code=501, detail="Integração com Stripe não disponível")

    resultado = consumir_relatorio(user_id)
    if not resultado.get("success"):
        raise HTTPException(status_code=400, detail=resultado.get("error", "Não há relatórios disponíveis"))

    return resultado

@app.get("/stripe/pagamentos/{user_id}")
async def historico_pagamentos(user_id: str):
    """
    Obtém o histórico de pagamentos do usuário
    """
    if not stripe_available:
        raise HTTPException(status_code=503, detail="Serviço Stripe não está disponível")
    
    resultado = obter_historico_pagamentos(user_id)
    
    if resultado.get("success"):
        return resultado
    else:
        raise HTTPException(status_code=400, detail=resultado.get("error", "Erro ao obter histórico de pagamentos"))

@app.post("/pagamentos/")
async def salvar_pagamento(pagamento_data: PagamentoData):
    """
    Salva os dados de pagamento no Firestore
    """
    if not firebase_available:
        raise HTTPException(status_code=503, detail="Serviço Firebase não está disponível")
    
    try:
        # Obter instância do Firestore
        from firebase_admin import firestore
        db = get_firestore_db()
        
        # Preparar os dados do pagamento
        payment_data = {
            "subscription": {
                "autoRenew": pagamento_data.auto_renew,
                "endDate": pagamento_data.end_date,
                "paymentInfo": {
                    "amount": pagamento_data.amount,
                    "lastPaymentDate": pagamento_data.start_date,
                    "paymentId": pagamento_data.payment_id,
                    "paymentMethod": pagamento_data.payment_method,
                    "planId": pagamento_data.plan_id,
                    "planName": pagamento_data.plan_name
                },
                "creditosPlano": pagamento_data.creditos_plano,  # Novo campo para os créditos fixos
                "reportsLeft": pagamento_data.reports_left,
                "startDate": pagamento_data.start_date
            }
        }
        
        if pagamento_data.telefone:
            payment_data["telefone"] = pagamento_data.telefone
        
        payment_data["temPlano"] = True
        payment_data["userId"] = pagamento_data.user_id
        
        # Salvar na coleção "pagamentos"
        pagamento_ref = db.collection('pagamentos').document()
        pagamento_ref.set(payment_data)
        
        # Atualizar o documento do usuário com a referência ao pagamento
        usuario_ref = db.collection('usuarios').document(pagamento_data.user_id)
        usuario_ref.set({
            'pagamentos': {
                pagamento_ref.id: {
                    'data': pagamento_data.start_date
                }
            }
        }, merge=True)
        
        return {"success": True, "pagamento_id": pagamento_ref.id}
    
    except Exception as e:
        logger.error(f"Erro ao salvar pagamento: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Erro ao salvar pagamento: {str(e)}")

# Endpoints adicionais para gestão de planos
@app.get("/stripe/plano/{user_id}")
async def obter_plano_usuario(user_id: str):
    """Obtém informações do plano do usuário"""
    if not stripe_available:
        raise HTTPException(status_code=501, detail="Integração com Stripe não disponível")

    try:
        db = get_firestore_db()
        user_doc = db.collection('usuarios').document(user_id).get()
        
        if not user_doc.exists:
            return {
                "success": True,
                "tem_plano": False,
                "message": "Usuário não possui plano ativo"
            }
            
        user_data = user_doc.to_dict()
        subscription = user_data.get('subscription', {})
        
        if not subscription:
            return {
                "success": True,
                "tem_plano": False,
                "message": "Usuário não possui plano ativo"
            }
        
        # Verificar se a assinatura expirou
        end_date = subscription.get('endDate')
        if end_date and not subscription.get('autoRenew'):
            if isinstance(end_date, datetime.datetime):
                if end_date < datetime.datetime.now():
                    return {
                        "success": True,
                        "tem_plano": False,
                        "message": "Plano expirado"
                    }
        
        return {
            "success": True,
            "tem_plano": True,
            "plano": {
                "nome": subscription.get('planName', 'Desconhecido'),
                "relatorios_restantes": subscription.get('reportsLeft', 0),
                "renovacao_automatica": subscription.get('autoRenew', False),
                "data_inicio": subscription.get('startDate'),
                "data_fim": subscription.get('endDate')
            }
        }
        
    except Exception as e:
        logger.error(f"Erro ao obter plano do usuário: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Erro ao obter plano do usuário: {str(e)}")

@app.post("/stripe/assinatura/cancelar/{user_id}")
async def cancelar_assinatura(user_id: str):
    """Cancela a assinatura do usuário"""
    if not stripe_available:
        raise HTTPException(status_code=501, detail="Integração com Stripe não disponível")

    try:
        # Buscar dados do usuário
        db = get_firestore_db()
        user_doc = db.collection('usuarios').document(user_id).get()
        
        if not user_doc.exists:
            raise HTTPException(status_code=404, detail="Usuário não encontrado")
            
        user_data = user_doc.to_dict()
        subscription = user_data.get('subscription', {})
        subscription_id = subscription.get('stripeSubscriptionId')
        
        if not subscription_id:
            raise HTTPException(status_code=400, detail="Usuário não possui assinatura ativa")
            
        # Cancelar assinatura no Stripe
        stripe.Subscription.modify(
            subscription_id,
            cancel_at_period_end=True
        )
        
        # Atualizar no Firestore
        db.collection('usuarios').document(user_id).update({
            'subscription.autoRenew': False,
            'subscription.canceledAt': firestore.SERVER_TIMESTAMP
        })
        
        return {
            "success": True,
            "message": "Assinatura cancelada com sucesso"
        }
        
    except Exception as e:
        logger.error(f"Erro ao cancelar assinatura: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Erro ao cancelar assinatura: {str(e)}")

@app.get("/stripe/planos/")
async def listar_planos():
    """Lista os planos disponíveis"""
    if not stripe_available:
        raise HTTPException(status_code=501, detail="Integração com Stripe não disponível")
    
    from app.stripe_service import PLANOS
    
    # Formatar os planos para o frontend
    planos_formatados = []
    for plano_id, plano in PLANOS.items():
        planos_formatados.append({
            "id": plano_id,
            "nome": plano["name"],
            "descricao": plano["description"],
            "preco": plano["price"] / 100,  # Converter de centavos para reais
            "relatorios": plano["reports"],
            "desconto": plano["discount"]
        })
    
    return {
        "success": True,
        "planos": planos_formatados
    }

@app.post("/pagamento/pix/")
async def pagamento_pix(pagamento: PixPagamentoRequest):
    """Cria um pagamento via PIX"""
    if not stripe_available or not firebase_available:
        raise HTTPException(status_code=503, detail="Serviços necessários não estão disponíveis")
    
    resultado = criar_pagamento_pix(
        pagamento.user_id, 
        pagamento.plano_id, 
        pagamento.telefone
    )
    
    if resultado.get("success"):
        return resultado
    else:
        raise HTTPException(status_code=400, detail=resultado.get("error", "Erro ao criar pagamento PIX"))