from fastapi import FastAPI, UploadFile, File, HTTPException, Form, Body, Request
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional, Dict, Any
from openai import OpenAI
from .utils import extract_text_from_document
import os
import logging
import json
import io
from pathlib import Path
from dotenv import load_dotenv
from pydantic import BaseModel

# Importar módulos Firebase
try:
    from app.firebase_service import initialize_firebase, save_report
    firebase_available = True
except ImportError:
    firebase_available = False
    logging.warning("Módulo firebase_service não encontrado. Funcionalidades de Firebase não estarão disponíveis.")

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

def load_prompt_from_file(prompt_file_path: str = "prompt.txt") -> str:
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
        
        # Limita o tamanho do texto se for muito grande (GPT tem limite de tokens)
        max_chars = 50000  # Aproximadamente 12-15k tokens
        if len(combined_text) > max_chars:
            logger.warning(f"Texto muito longo ({len(combined_text)} chars). Truncando para {max_chars} chars.")
            combined_text = combined_text[:max_chars] + "\n\n[TEXTO TRUNCADO DEVIDO AO TAMANHO]"
        
        user_prompt = f"""Analise o seguinte conteúdo dos documentos empresariais:

{combined_text}

Forneça uma análise completa seguindo a estrutura solicitada."""

        logger.info("Enviando texto para análise da OpenAI...")
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",  # Ou "gpt-4" se preferir
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            max_tokens=2000,  # Ajuste conforme necessário
            temperature=0.3   # Baixa para respostas mais consistentes
        )
        
        analysis = response.choices[0].message.content
        token_usage = {
            "prompt_tokens": response.usage.prompt_tokens,
            "completion_tokens": response.usage.completion_tokens,
            "total_tokens": response.usage.total_tokens
        }
        
        logger.info(f"Análise concluída. Tamanho da resposta: {len(analysis)} caracteres")
        logger.info(f"Tokens utilizados: {token_usage}")
        
        return analysis, token_usage
        
    except Exception as e:
        logger.error(f"Erro ao chamar OpenAI: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Erro ao processar análise: {str(e)}")

@app.post("/analyze/")
async def analyze(
    files: List[UploadFile] = File(...),
    planning_data: Optional[str] = Form(None)
):
    logger.info(f"Recebido {len(files)} arquivos para análise")
    
    if not files:
        raise HTTPException(status_code=400, detail="Nenhum arquivo enviado.")

    combined_text = ""
    processed_files = []
    
    # Processar dados de planejamento, se fornecidos
    if planning_data:
        try:
            planning_json = json.loads(planning_data)
            logger.info(f"Dados de planejamento recebidos: {planning_json}")
            
            combined_text += "=== DADOS DE PLANEJAMENTO ===\n"
            
            # Adicionar segmento
            if planning_json.get("segment"):
                segment = planning_json["segment"]
                if segment == "Outro" and planning_json.get("otherSegment"):
                    segment = planning_json["otherSegment"]
                combined_text += f"Segmento da Empresa: {segment}\n"
            
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
                
            combined_text += "\n\n"
        except json.JSONDecodeError as e:
            logger.error(f"Erro ao decodificar dados de planejamento: {str(e)}")
            # Continuar mesmo com erro nos dados de planejamento
    
    # Primeira etapa: Extrair texto de todos os arquivos
    for i, file in enumerate(files):
        logger.info(f"Processando arquivo {i+1}: {file.filename}, tipo: {file.content_type}")
        
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
                
            combined_text += f"\n=== DOCUMENTO: {file.filename} ===\n"
            combined_text += text + "\n\n"
            
            processed_files.append({
                "filename": file.filename,
                "status": "processado",
                "text_length": len(text)
            })
            
            logger.info(f"Arquivo {file.filename} processado com sucesso. Texto extraído: {len(text)} caracteres")
            
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
    
    logger.info(f"Extração concluída. Total de texto: {len(combined_text)} caracteres")
    
    # Segunda etapa: Enviar para OpenAI para análise
    try:
        analysis, token_usage = await analyze_with_openai(combined_text)
        
        return {
            "success": True,
            "analysis": analysis,
            "processed_files": processed_files,
            "total_text_length": len(combined_text),
            "files_processed": len([f for f in processed_files if f['status'] == 'processado']),
            "token_usage": token_usage
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
    """
    Endpoint para salvar relatório no Firebase.
    
    Recebe dados do relatório e arquivos para salvar no Firestore (sem Storage).
    """
    if not firebase_available:
        raise HTTPException(
            status_code=501, 
            detail="Funcionalidade de Firebase não está disponível no backend."
        )
    
    try:
        # Converter os dados do relatório de string JSON para dicionário
        try:
            report_data_dict = json.loads(report_data)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Dados do relatório inválidos. JSON esperado.")
            
        user_id = report_data_dict.get("user_id")
        user_name = report_data_dict.get("user_name")
        planning_data = report_data_dict.get("planning_data", {})
        report_content = report_data_dict.get("report_content", "")
        
        logger.info(f"Recebendo solicitação para salvar relatório para o usuário {user_id}")
        
        if not user_id or not user_name:
            raise HTTPException(status_code=400, detail="ID do usuário e nome são obrigatórios.")
        
        # Preparar documentos para upload (apenas metadados)
        analysis_files = {}
        if files:
            for file in files:
                # Tenta determinar o tipo do documento pelo nome
                file_name = file.filename.lower()
                doc_type = None
                
                if 'imposto' in file_name or 'ir' in file_name:
                    doc_type = 'incomeTax'
                elif 'registro' in file_name:
                    doc_type = 'registration'
                elif 'fiscal' in file_name or 'situacao' in file_name:
                    doc_type = 'taxStatus'
                elif 'faturamento' in file_name and 'fiscal' in file_name:
                    doc_type = 'taxBilling'
                elif 'faturamento' in file_name and 'gerencial' in file_name:
                    doc_type = 'managementBilling'
                else:
                    # Para arquivos não identificados, usar o nome original
                    doc_type = f"document_{len(analysis_files)}"
                
                # Apenas registrar metadados do arquivo
                file_info = {
                    "filename": file.filename,
                    "content_type": file.content_type,
                    "size": 0  # Não podemos obter o tamanho sem ler o arquivo
                }
                analysis_files[doc_type] = file_info
        
        # Salvar relatório no Firebase
        result = save_report(
            user_id=user_id,
            user_name=user_name,
            planning_data=planning_data,
            analysis_files=analysis_files,
            report_content=report_content
        )
        
        if not result["success"]:
            raise HTTPException(
                status_code=500, 
                detail=f"Erro ao salvar relatório: {result.get('error', 'Erro desconhecido')}"
            )
        
        return {
            "success": True,
            "report_id": result.get("report_id", ""),
            "message": "Relatório salvo com sucesso no Firebase"
        }
        
    except Exception as e:
        logger.error(f"Erro ao salvar relatório: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao salvar relatório: {str(e)}"
        )

@app.get("/firebase_status/")
async def firebase_status():
    """Verifica se a integração com Firebase está disponível e configurada"""
    if not firebase_available:
        return {"available": False, "reason": "Módulo firebase_service não encontrado"}
    
    try:
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

# Inicializar Firebase ao iniciar a aplicação, se disponível
if firebase_available:
    try:
        is_initialized = initialize_firebase()
        if is_initialized:
            logger.info("Firebase inicializado durante a inicialização da aplicação")
        else:
            logger.warning("Falha ao inicializar Firebase durante inicialização da aplicação")
    except Exception as e:
        logger.error(f"Erro ao inicializar Firebase durante a inicialização da aplicação: {str(e)}")