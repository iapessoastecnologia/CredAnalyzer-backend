import fitz  # PyMuPDF
from fastapi import UploadFile
import os
import tempfile
import pytesseract
from PIL import Image
import io
import docx
import logging

logger = logging.getLogger(__name__)

async def extract_text_from_document(file: UploadFile) -> str:
    """Extrai texto de diferentes tipos de arquivo"""
    content_type = file.content_type
    logger.info(f"Extraindo texto de arquivo tipo: {content_type}")
    
    # Ler o conteúdo do arquivo uma vez
    file_content = await file.read()
    
    # Para arquivos PDF
    if content_type == "application/pdf":
        text = extract_text_from_pdf_bytes(file_content)
        print(f"\n----- CONTEÚDO EXTRAÍDO DO PDF: {file.filename} -----")
        print(f"{text[:500]}...")  # Mostra apenas os primeiros 500 caracteres
        print(f"----- FIM DO CONTEÚDO EXTRAÍDO ({len(text)} caracteres) -----\n")
        return text
    
    # Para imagens JPEG/PNG
    elif content_type in ["image/jpeg", "image/png"]:
        text = extract_text_from_image_bytes(file_content)
        print(f"\n----- CONTEÚDO EXTRAÍDO DA IMAGEM: {file.filename} -----")
        print(f"{text[:500]}...")  # Mostra apenas os primeiros 500 caracteres
        print(f"----- FIM DO CONTEÚDO EXTRAÍDO ({len(text)} caracteres) -----\n")
        return text
    
    # Para documentos Word
    elif content_type in ["application/msword", 
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"]:
        text = extract_text_from_word_bytes(file_content)
        print(f"\n----- CONTEÚDO EXTRAÍDO DO WORD: {file.filename} -----")
        print(f"{text[:500]}...")  # Mostra apenas os primeiros 500 caracteres
        print(f"----- FIM DO CONTEÚDO EXTRAÍDO ({len(text)} caracteres) -----\n")
        return text
    
    # Tipo não suportado
    else:
        logger.warning(f"Tipo de arquivo não suportado: {content_type}")
        return ""

def extract_text_from_pdf_bytes(file_content: bytes) -> str:
    """Extrai texto de PDF a partir de bytes"""
    try:
        content = ''
        with fitz.open(stream=file_content, filetype="pdf") as doc:
            for page_num, page in enumerate(doc):
                page_text = page.get_text()
                if page_text.strip():  # Só adiciona se a página tem conteúdo
                    content += f"\n--- Página {page_num + 1} ---\n"
                    content += page_text
        logger.info(f"PDF processado: {len(content)} caracteres extraídos")
        return content
    except Exception as e:
        logger.error(f"Erro ao processar PDF: {str(e)}")
        raise Exception(f"Erro ao processar PDF: {str(e)}")

def extract_text_from_image_bytes(file_content: bytes) -> str:
    """Extrai texto de uma imagem usando OCR"""
    try:
        image = Image.open(io.BytesIO(file_content))
        text = pytesseract.image_to_string(image, lang='por')
        logger.info(f"Imagem processada: {len(text)} caracteres extraídos")
        return text
    except Exception as e:
        logger.error(f"Erro ao processar imagem: {str(e)}")
        # Para imagens, retornar string vazia em vez de erro, pois OCR pode falhar
        return f"[Erro ao processar imagem: {str(e)}]"

def extract_text_from_word_bytes(file_content: bytes) -> str:
    """Extrai texto de um documento Word"""
    try:
        # Salva o arquivo temporariamente
        with tempfile.NamedTemporaryFile(delete=False, suffix='.docx') as temp_file:
            temp_file.write(file_content)
            temp_path = temp_file.name
        
        # Processa o documento Word
        doc = docx.Document(temp_path)
        paragraphs = []
        
        for paragraph in doc.paragraphs:
            if paragraph.text.strip():  # Só adiciona parágrafos não vazios
                paragraphs.append(paragraph.text)
        
        content = '\n'.join(paragraphs)
        
        # Remove o arquivo temporário
        os.unlink(temp_path)
        
        logger.info(f"Documento Word processado: {len(content)} caracteres extraídos")
        return content
        
    except Exception as e:
        logger.error(f"Erro ao processar documento Word: {str(e)}")
        raise Exception(f"Erro ao processar documento Word: {str(e)}")

# Funções antigas para compatibilidade (deprecated)
def extract_text_from_pdf(file: UploadFile) -> str:
    """Função deprecated - use extract_text_from_pdf_bytes"""
    logger.warning("Usando função deprecated extract_text_from_pdf")
    file.file.seek(0)
    content = file.file.read()
    return extract_text_from_pdf_bytes(content)

def extract_text_from_image(file: UploadFile) -> str:
    """Função deprecated - use extract_text_from_image_bytes"""
    logger.warning("Usando função deprecated extract_text_from_image")
    file.file.seek(0)
    content = file.file.read()
    return extract_text_from_image_bytes(content)

def extract_text_from_word(file: UploadFile) -> str:
    """Função deprecated - use extract_text_from_word_bytes"""
    logger.warning("Usando função deprecated extract_text_from_word")
    file.file.seek(0)
    content = file.file.read()
    return extract_text_from_word_bytes(content)