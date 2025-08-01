import fitz  # PyMuPDF
from fastapi import UploadFile
import os
import tempfile
import pytesseract
from PIL import Image
import io
import re
import docx
import logging
import camelot
import pandas as pd
from typing import Dict, Any, Tuple

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

# def extract_scr_data_from_pdf(file_content: bytes, filename: str) -> dict:
#     """
#     Extrai dados específicos de um arquivo SCR (PDF) convertendo para DataFrame
#     e buscando valores nas células específicas. Também salva a planilha gerada.
    
#     Args:
#         file_content: Conteúdo do arquivo em bytes
#         filename: Nome do arquivo
        
#     Returns:
#         Dict contendo os valores de dívidas em dia e vencidas
#     """
#     try:
#         # Importar dependências necessárias
#         import camelot
#         import pandas as pd
        
#         # Criar pasta planilhas_geradas se não existir
#         planilhas_dir = "planilhas_geradas"
#         if not os.path.exists(planilhas_dir):
#             os.makedirs(planilhas_dir)
#             logger.info(f"Pasta {planilhas_dir} criada")
        
#         # Salvar temporariamente o PDF para o camelot processar
#         with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as temp_file:
#             temp_file.write(file_content)
#             temp_path = temp_file.name
        
#         logger.info(f"Processando SCR: {filename}")
        
#         # Usar camelot para extrair tabelas
#         tabelas = camelot.read_pdf(temp_path, pages="all")
        
#         # Combinar todas as tabelas em um único DataFrame
#         dfs = []
#         for i, tabela in enumerate(tabelas):
#             df = tabela.df
#             df = df.replace('\n', ' ', regex=True)
#             dfs.append(df)
        
#         # Concatenar todos os DataFrames
#         if dfs:
#             df_final = pd.concat(dfs, ignore_index=True)
            
#             # Salvar a planilha gerada
#             excel_filename = filename.replace('.pdf', '.xlsx')
#             excel_path = os.path.join(planilhas_dir, excel_filename)
            
#             try:
#                 df_final.to_excel(excel_path, index=False)
#                 logger.info(f"Planilha salva em: {excel_path}")
#                 print(f"✅ Planilha gerada e salva: {excel_path}")
#             except Exception as e:
#                 logger.error(f"Erro ao salvar planilha: {str(e)}")
#                 print(f"⚠️ Erro ao salvar planilha: {str(e)}")
            
#             # Extrair valores específicos das células C4 e D4
#             # Ajustando para o formato do DataFrame do camelot (índices começam em 0)
#             divida_em_dia = "0.00"  # Valor padrão se não encontrar
#             divida_vencida = "0.00"  # Valor padrão se não encontrar
            
#             # Verificar se temos pelo menos 4 linhas e 4 colunas
#             if df_final.shape[0] >= 4 and df_final.shape[1] >= 4:
#                 # Extrair valores (ajustando para índices 0-based)
#                 divida_em_dia = df_final.iloc[3, 2] if not pd.isna(df_final.iloc[3, 2]) else "0.00"
#                 divida_vencida = df_final.iloc[3, 3] if not pd.isna(df_final.iloc[3, 3]) else "0.00"
            
#             # Limpar e formatar os valores
#             divida_em_dia = divida_em_dia.strip().replace("R$", "").replace(".", "").replace(",", ".")
#             divida_vencida = divida_vencida.strip().replace("R$", "").replace(".", "").replace(",", ".")
            
#             # Converter para float
#             try:
#                 divida_em_dia = float(divida_em_dia)
#             except ValueError:
#                 divida_em_dia = 0.0
                
#             try:
#                 divida_vencida = float(divida_vencida)
#             except ValueError:
#                 divida_vencida = 0.0
            
#             # Remover arquivo temporário
#             os.unlink(temp_path)
            
#             logger.info(f"SCR processado: Dívida em dia: R$ {divida_em_dia}, Dívida vencida: R$ {divida_vencida}")
            
#             # Retornar os dados estruturados
#             return {
#                 "divida_em_dia": divida_em_dia,
#                 "divida_vencida": divida_vencida,
#                 "total_dividas": divida_em_dia + divida_vencida,
#                 "arquivo": filename,
#                 "planilha_gerada": excel_path
#             }
#         else:
#             logger.warning(f"Nenhuma tabela encontrada no arquivo SCR: {filename}")
#             os.unlink(temp_path)
#             return {
#                 "divida_em_dia": 0.0,
#                 "divida_vencida": 0.0,
#                 "total_dividas": 0.0,
#                 "arquivo": filename,
#                 "erro": "Nenhuma tabela encontrada no arquivo"
#             }
            
#     except ImportError as e:
#         logger.error(f"Erro ao importar dependências para processar SCR: {str(e)}")
#         return {
#             "divida_em_dia": 0.0,
#             "divida_vencida": 0.0,
#             "total_dividas": 0.0,
#             "arquivo": filename,
#             "erro": f"Erro ao importar dependências: {str(e)}"
#         }
#     except Exception as e:
#         logger.error(f"Erro ao processar SCR {filename}: {str(e)}")
#         return {
#             "divida_em_dia": 0.0,
#             "divida_vencida": 0.0,
#             "total_dividas": 0.0,
#             "arquivo": filename,
#             "erro": f"Erro ao processar: {str(e)}"
#         }


def encontrar(comeco, final, fonte, meio=r'.*'):
    """
    Função auxiliar para encontrar texto entre padrões específicos
    """
    padrao = comeco + meio + final
    resultado = re.findall(padrao, fonte, re.DOTALL)
    if len(resultado) > 0:
        resultado = resultado[0]
        resultado = resultado.replace(re.findall(comeco, fonte)[0], "").replace(re.findall(final, fonte)[0], "")
    else:
        resultado = "###"
    return resultado

def extrair_texto_pdf(pdf_bytes):
    """
    Extrai texto de um PDF a partir de bytes
    """
    txt = ""
    try:
        pdf_stream = io.BytesIO(pdf_bytes)
        from PyPDF2 import PdfReader
        leitor = PdfReader(pdf_stream)
        num_paginas = len(leitor.pages)
        
        for pagina_num in range(num_paginas):
            pagina = leitor.pages[pagina_num]
            texto = pagina.extract_text()
            txt = txt + texto
            
    except Exception as e:
        print(f"Erro ao extrair texto do PDF: {str(e)}")
        
    return txt

def pdf_para_dataframe(pdf_bytes):
    """
    Converte PDF para DataFrame usando camelot
    """
    try:
        # Criar arquivo temporário para o camelot processar
        with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as temp_file:
            temp_file.write(pdf_bytes)
            temp_file.flush()
            temp_path = temp_file.name
        
        print(f"📄 Processando PDF com camelot...")
        
        # Processar PDF com camelot
        tabelas = camelot.read_pdf(temp_path, pages="all")
        print(f"📊 Encontradas {len(tabelas)} tabelas no PDF")
        
        dfs = []
        
        for i, tabela in enumerate(tabelas):
            df = tabela.df  # DataFrame da tabela
            df = df.replace('\n', ' ', regex=True)
            print(f"📋 Tabela {i+1}: {df.shape[0]} linhas x {df.shape[1]} colunas")
            dfs.append(df)
        
        if dfs:
            df_final = pd.concat(dfs, ignore_index=True)
            print(f"📊 DataFrame final: {df_final.shape[0]} linhas x {df_final.shape[1]} colunas")
        else:
            df_final = pd.DataFrame()
            print("⚠️ Nenhuma tabela encontrada no PDF")
            
        # Limpar arquivo temporário
        import os
        os.unlink(temp_path)
        
        return df_final
        
    except Exception as e:
        print(f"❌ Erro ao processar PDF: {str(e)}")
        return pd.DataFrame()

# Função removida - lógica integrada diretamente na função principal

def extract_scr_data_from_pdf(pdf_data: bytes, filename: str = None) -> Dict[str, Any]:
    """
    Função principal para extrair dados de dívida de documentos SCR em PDF
    
    Args:
        pdf_data (bytes): Dados do arquivo PDF em bytes
        filename (str, optional): Nome do arquivo original
    
    Returns:
        Dict contendo:
        - divida_em_dia (float): Valor da dívida em dia
        - divida_vencida (float): Valor da dívida vencida
        - total_dividas (float): Total das dívidas
        - erro (str): Mensagem de erro se houver
        - planilha_gerada (str): Caminho/nome da planilha Excel gerada
        - empresa_nome (str): Nome da empresa
        - empresa_cnpj (str): CNPJ da empresa
    """
    
    resultado = {
        'divida_em_dia': 0.0,
        'divida_vencida': 0.0,
        'total_dividas': 0.0,
        'erro': None,
        'planilha_gerada': None,
        'empresa_nome': "Não identificado",
        'empresa_cnpj': "Não identificado"
    }
    
    try:
        # 1. Converter PDF para DataFrame
        df = pdf_para_dataframe(pdf_data)
        
        # 2. Extrair texto completo do PDF para informações adicionais
        texto_completo = extrair_texto_pdf(pdf_data)
        
        # 3. Extrair informações da empresa do texto
        nome_empresa = encontrar(r'Razão Social:', r'\n', texto_completo)
        cnpj = encontrar(r'CNPJ:', r'\n', texto_completo)
        
        resultado['empresa_nome'] = nome_empresa if nome_empresa != "###" else "Não identificado"
        resultado['empresa_cnpj'] = cnpj if cnpj != "###" else "Não identificado"
        
        # 4. Extrair dívidas das células específicas (4C e 4D)
        if df.empty:
            resultado['erro'] = "DataFrame vazio - não foi possível extrair tabelas do PDF"
            return resultado
        
        try:
            # Debug: Mostrar informações do DataFrame
            print(f"📊 DataFrame shape: {df.shape}")
            print(f"📊 Colunas disponíveis: {len(df.columns)}")
            print(f"📊 Linhas disponíveis: {len(df)}")
            
            # Mostrar as primeiras linhas para debug
            print("📊 Primeiras 10 linhas do DataFrame:")
            for i in range(min(10, len(df))):
                print(f"Linha {i}: {df.iloc[i].tolist()}")
            
            # Extrair dívida em dia (posição [2,1])
            if len(df) > 2 and len(df.columns) > 1:
                divida_em_dia_raw = df.iloc[2, 1] if pd.notna(df.iloc[2, 1]) else "0"
                print(f"🔍 Dívida em dia (raw): '{divida_em_dia_raw}'")
                
                # Limpar e converter valor usando padrão brasileiro
                divida_em_dia_clean = re.sub(r'[^\d,.-]', '', str(divida_em_dia_raw))
                print(f"🔍 Dívida em dia (raw): '{divida_em_dia_raw}'")
                print(f"🔍 Dívida em dia (após regex): '{divida_em_dia_clean}'")
                
                # Converter padrão brasileiro para float
                # Ex: "427.909,68" -> 427909.68
                if divida_em_dia_clean:
                    # Remover pontos de milhares e trocar vírgula por ponto
                    divida_em_dia_clean = divida_em_dia_clean.replace('.', '').replace(',', '.')
                    print(f"🔍 Dívida em dia (convertida): '{divida_em_dia_clean}'")
                
                resultado['divida_em_dia'] = float(divida_em_dia_clean) if divida_em_dia_clean else 0.0
                print(f"✅ Dívida em dia (final): R$ {resultado['divida_em_dia']:.2f}")
            else:
                print(f"⚠️ DataFrame muito pequeno para posição [2,1]: {len(df)} linhas, {len(df.columns)} colunas")
            
            # Extrair dívida vencida (posição [2,2])
            if len(df) > 2 and len(df.columns) > 2:
                divida_vencida_raw = df.iloc[2, 2] if pd.notna(df.iloc[2, 2]) else "0"
                print(f"🔍 Dívida vencida (raw): '{divida_vencida_raw}'")
                
                # Limpar e converter valor usando padrão brasileiro
                divida_vencida_clean = re.sub(r'[^\d,.-]', '', str(divida_vencida_raw))
                print(f"🔍 Dívida vencida (raw): '{divida_vencida_raw}'")
                print(f"🔍 Dívida vencida (após regex): '{divida_vencida_clean}'")
                
                # Converter padrão brasileiro para float
                # Ex: "427.909,68" -> 427909.68
                if divida_vencida_clean:
                    # Remover pontos de milhares e trocar vírgula por ponto
                    divida_vencida_clean = divida_vencida_clean.replace('.', '').replace(',', '.')
                    print(f"🔍 Dívida vencida (convertida): '{divida_vencida_clean}'")
                
                resultado['divida_vencida'] = float(divida_vencida_clean) if divida_vencida_clean else 0.0
                print(f"✅ Dívida vencida (final): R$ {resultado['divida_vencida']:.2f}")
            else:
                print(f"⚠️ DataFrame muito pequeno para posição [2,2]: {len(df)} linhas, {len(df.columns)} colunas")
            
            # Calcular total
            resultado['total_dividas'] = resultado['divida_em_dia'] + resultado['divida_vencida']
            print(f"💰 Total de dívidas: R$ {resultado['total_dividas']:.2f}")
            
            # Se não encontrou valores, tentar buscar em outras posições
            if resultado['divida_em_dia'] == 0.0 and resultado['divida_vencida'] == 0.0:
                print("🔍 Valores zerados, tentando buscar em outras posições...")
                
                # Buscar por padrões de valores monetários em todo o DataFrame
                for i in range(min(10, len(df))):  # Verificar as primeiras 10 linhas
                    for j in range(min(10, len(df.columns))):  # Verificar as primeiras 10 colunas
                        cell_value = str(df.iloc[i, j])
                        if 'R$' in cell_value or re.search(r'\d+[,.]\d{2}', cell_value):
                            print(f"💰 Valor encontrado na posição [{i},{j}]: '{cell_value}'")
                
        except Exception as e:
            resultado['erro'] = f"Erro ao extrair dívidas das células 4C e 4D: {str(e)}"
            print(f"❌ Erro na extração: {str(e)}")
            return resultado
        
        # 5. Gerar arquivo Excel
        try:
            # Criar nome do arquivo Excel baseado no PDF original
            excel_filename = filename.replace('.pdf', '.xlsx') if filename else 'SCR_convertido.xlsx'
            
            # Salvar DataFrame como Excel (aqui você pode definir o caminho desejado)
            # Por enquanto, apenas indicamos que foi gerado
            resultado['planilha_gerada'] = excel_filename
            
            # Se você quiser salvar fisicamente o arquivo, descomente as linhas abaixo:
            # excel_path = f"planilhas_excel/{excel_filename}"
            # df.to_excel(excel_path, index=False, engine='openpyxl')
            # resultado['planilha_gerada'] = excel_path
            
        except Exception as e:
            # Não é um erro crítico se não conseguir gerar o Excel
            resultado['planilha_gerada'] = f"Erro ao gerar Excel: {str(e)}"
            
    except Exception as e:
        resultado['erro'] = f"Erro geral no processamento: {str(e)}"
    
    return resultado