"""
Helper para logs detalhados
"""
import logging
import json

logger = logging.getLogger(__name__)

def log_document_types(files, document_types):
    """
    Log detalhado dos tipos de documentos
    """
    if not document_types:
        logger.info("Nenhum document_types fornecido")
        print("Nenhum document_types fornecido")
        return
    
    try:
        if isinstance(document_types, str):
            doc_types = json.loads(document_types)
        else:
            doc_types = document_types
            
        print("\n===== TIPOS DE DOCUMENTOS RECEBIDOS =====")
        print(f"Formato: {type(doc_types)}")
        print(f"Conteúdo: {doc_types}")
        
        if not isinstance(doc_types, dict):
            print(f"AVISO: document_types não é um dicionário. Valor: {doc_types}")
            return
            
        # Mostrar informações de cada arquivo
        for i, file in enumerate(files):
            str_index = str(i)
            if str_index in doc_types:
                print(f"Arquivo {i}: {file.filename} -> Tipo: {doc_types[str_index]}")
            else:
                print(f"Arquivo {i}: {file.filename} -> Tipo não especificado")
                
        print("========================================\n")
        
    except Exception as e:
        logger.error(f"Erro ao processar log de tipos de documentos: {str(e)}")
        print(f"Erro ao processar log: {str(e)}")