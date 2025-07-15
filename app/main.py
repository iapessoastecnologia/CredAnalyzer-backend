from fastapi import FastAPI, UploadFile, File, HTTPException, Form, Body, Request, Query, Depends, Header
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
import datetime

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

Forneça uma análise completa seguindo a estrutura solicitada. 
Note que pode haver múltiplos documentos para cada categoria (ex: múltiplos arquivos de Faturamento Fiscal ou SPC/Serasa).
Considere todos os documentos em sua análise, mesmo que sejam da mesma categoria."""

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
            
            # Identificar categoria do arquivo para uma melhor organização no texto
            category = None
            filename = file.filename.lower()
            
            if 'imposto' in filename or 'irpf' in filename:
                category = 'Imposto de Renda'
            elif 'registro' in filename or 'contrato' in filename:
                category = 'Registro'
            elif 'fiscal' in filename:
                category = 'Situação Fiscal'
            elif 'faturamento' in filename:
                if 'gerencial' in filename:
                    category = 'Faturamento Gerencial'
                else:
                    category = 'Faturamento Fiscal'
            elif 'spc' in filename or 'serasa' in filename:
                category = 'SPC e Serasa'
            elif 'demonstrativo' in filename or 'extrato' in filename:
                category = 'Demonstrativo'
            else:
                category = 'Documento Adicional'
            
            combined_text += f"\n=== DOCUMENTO ({category}): {file.filename} ===\n"
            combined_text += text + "\n\n"
            
            processed_files.append({
                "filename": file.filename,
                "status": "processado",
                "text_length": len(text),
                "category": category
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