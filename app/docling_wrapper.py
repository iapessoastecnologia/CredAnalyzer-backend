"""
Wrapper para docling que converte documentos para imagens e usa OpenAI Vision
para processá-los ao invés de converter para markdown.
"""
import io
import os
import logging
import tempfile
import base64
from typing import Optional
import json
from PIL import Image
import pdf2image  # Precisamos instalar: pip install pdf2image
from openai import OpenAI
import re
import uuid

logger = logging.getLogger(__name__)

# Inicializar o cliente OpenAI (certifique-se de que a chave API esteja definida no ambiente)
client = OpenAI()

class DocumentWrapper:
    """
    Wrapper que converte documentos para imagens e processa usando
    OpenAI Vision API em vez de convertê-los para markdown.
    """
    
    def __init__(self):
        """Inicializa o wrapper."""
        self.converter = None
        # Verificar se o cliente OpenAI está configurado corretamente
        try:
            # Tentar obter a chave do ambiente
            self.openai_api_key = os.environ.get("OPENAI_API_KEY")
            if not self.openai_api_key:
                logger.warning("OPENAI_API_KEY não encontrada no ambiente.")
            # Modelo vision a ser usado
            self.vision_model = "gpt-4o"
        except Exception as e:
            logger.error(f"Erro ao configurar cliente OpenAI: {str(e)}")
    
    def initialize(self):
        """Verifica se as dependências necessárias estão disponíveis."""
        try:
            # Verificar se o pdf2image está funcionando
            if not self.openai_api_key:
                logger.error("OPENAI_API_KEY não está configurada")
                return False
                
            logger.info("DocumentWrapper inicializado com sucesso")
            return True
        except ImportError as e:
            logger.error(f"Erro ao importar dependências: {str(e)}")
            return False
        except Exception as e:
            logger.error(f"Erro ao inicializar DocumentWrapper: {str(e)}")
            return False
    
    def convert_to_markdown(self, file_content, filename):
        """
        Converte conteúdo do arquivo para imagem e processa com OpenAI Vision.
        
        Args:
            file_content: Bytes do arquivo
            filename: Nome do arquivo original
            
        Returns:
            str: Conteúdo analisado (equivalente a markdown)
        """
        if not self.initialize():
            return f"[ERRO: DocumentWrapper não pôde ser inicializado]"
        
        try:
            # Gerar um nome para o arquivo temporário
            temp_id = str(uuid.uuid4())[:8]
            extension = os.path.splitext(filename)[1].lower()
            
            # Converter para imagem
            image_paths = []
            
            try:
                if extension == '.pdf':
                    # Processar PDF - converter para imagens
                    with tempfile.NamedTemporaryFile(delete=False, suffix=extension) as temp_file:
                        temp_file.write(file_content)
                        temp_path = temp_file.name
                    
                    # Converter PDF para imagens
                    poppler_path = r"C:/Users/Johan.Victor/Documents/poppler-24.08.0/Library/bin"  # Ajuste para o caminho real
                    images = pdf2image.convert_from_path(temp_path, dpi=150, poppler_path=poppler_path)
                    
                    # Salvar as imagens temporariamente
                    for i, img in enumerate(images):
                        tmp_dir = tempfile.gettempdir()
                        img_path = os.path.join(tmp_dir, f"doc_page_{temp_id}_{i}.png")
                        img.save(img_path, "PNG")
                        image_paths.append(img_path)
                    
                    # Remover o arquivo PDF temporário
                    os.unlink(temp_path)
                else:
                    # Para outros formatos, tentar abrir como imagem diretamente
                    tmp_dir = tempfile.gettempdir()
                    img_path = os.path.join(tmp_dir, f"doc_image_{temp_id}{extension}")
                    with open(img_path, 'wb') as f:
                        f.write(file_content)
                    image_paths.append(img_path)
                
                # Processar as imagens com OpenAI Vision
                logger.info(f"Processando {filename} com OpenAI Vision, {len(image_paths)} imagens")
                
                # Preparar as imagens para o prompt
                image_contents = []
                for img_path in image_paths:
                    with open(img_path, "rb") as img_file:
                        base64_image = base64.b64encode(img_file.read()).decode('utf-8')
                        image_contents.append(base64_image)
                
                # Criar mensagens para a API Vision
                messages = [
                    {
                        "role": "system", 
                        "content": "Você é um assistente especializado em extrair e formatar informações de documentos financeiros e empresariais. "
                                  "Formate o conteúdo de maneira organizada e estruturada, similar a markdown, preservando todos os dados "
                                  "e tabelas importantes. Mantenha a estrutura hierárquica do documento."
                    },
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": f"Analise este documento '{filename}' e extraia todo o conteúdo textual, mantendo a estrutura e formatação. "
                                                 f"Organize em formato estruturado similar a markdown, preservando tabelas e seções."}
                        ]
                    }
                ]
                
                # Adicionar as imagens ao conteúdo do usuário
                for base64_image in image_contents:
                    messages[1]["content"].append({
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{base64_image}"
                        }
                    })
                
                # Chamar a API Vision
                response = client.chat.completions.create(
                    model=self.vision_model,
                    messages=messages,
                    max_tokens=4000
                )
                
                # Obter o texto processado
                processed_text = response.choices[0].message.content
                
                # Limpar os arquivos de imagem temporários
                for img_path in image_paths:
                    if os.path.exists(img_path):
                        os.unlink(img_path)
                
                logger.info(f"Processamento de {filename} concluído com sucesso")
                return processed_text
            
            except Exception as e:
                logger.error(f"Erro no processamento da imagem {filename}: {str(e)}", exc_info=True)
                # Limpar os arquivos temporários em caso de erro
                for img_path in image_paths:
                    if os.path.exists(img_path):
                        try:
                            os.unlink(img_path)
                        except:
                            pass
                return f"[ERRO NO PROCESSAMENTO DA IMAGEM: {str(e)}]"
            
        except Exception as e:
            logger.error(f"Erro na conversão do documento {filename}: {str(e)}", exc_info=True)
            return f"[ERRO NA CONVERSÃO: {str(e)}]"