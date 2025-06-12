from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import List
from openai import OpenAI
from .utils import extract_text_from_document
import os
import logging
from pathlib import Path
from dotenv import load_dotenv

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

async def analyze_with_openai(combined_text: str) -> str:
    """Envia o texto extraído para análise da OpenAI"""
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
        logger.info(f"Análise concluída. Tamanho da resposta: {len(analysis)} caracteres")
        
        return analysis
        
    except Exception as e:
        logger.error(f"Erro ao chamar OpenAI: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Erro ao processar análise: {str(e)}")

@app.post("/analyze/")
async def analyze(files: List[UploadFile] = File(...)):
    logger.info(f"Recebido {len(files)} arquivos para análise")
    
    if not files:
        raise HTTPException(status_code=400, detail="Nenhum arquivo enviado.")

    combined_text = ""
    processed_files = []
    
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
        analysis = await analyze_with_openai(combined_text)
        
        return {
            "success": True,
            "analysis": analysis,
            "processed_files": processed_files,
            "total_text_length": len(combined_text),
            "files_processed": len([f for f in processed_files if f['status'] == 'processado'])
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