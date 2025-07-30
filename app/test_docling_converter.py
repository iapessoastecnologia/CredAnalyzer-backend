"""
Script de teste para verificar o funcionamento do DocumentConverter do docling.
Este teste verifica especificamente a funcionalidade de conversão de documentos.
"""
import os
import tempfile
import logging
import argparse
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_document_converter(test_file=None):
    """Testa a funcionalidade DocumentConverter com um arquivo específico ou exemplo."""
    try:
        print("\n===== IMPORTANDO DOCLING.DOCUMENT_CONVERTER =====")
        from docling.document_converter import DocumentConverter
        print("✅ Módulo DocumentConverter importado com sucesso")
        
        # Verificar versão do docling
        try:
            import docling
            print(f"Versão do docling: {getattr(docling, '__version__', 'Desconhecida')}")
            print(f"Diretório de instalação: {docling.__file__}")
        except Exception as e:
            print(f"⚠️ Não foi possível obter a versão do docling: {str(e)}")
        
        # Inicializar o conversor
        print("\n===== INICIALIZANDO DOCUMENT_CONVERTER =====")
        converter = DocumentConverter()
        print(f"✅ DocumentConverter inicializado: {converter}")
        
        # Se não foi fornecido um arquivo de teste, criar um arquivo de texto simples
        if test_file is None or not os.path.exists(test_file):
            print("\n===== CRIANDO ARQUIVO DE TESTE =====")
            
            # Criar arquivo temporário com conteúdo de teste
            with tempfile.NamedTemporaryFile(delete=False, suffix='.txt') as temp:
                content = """TESTE DE DOCUMENTO
                
                Este é um documento de teste para verificar o funcionamento do DocumentConverter.
                
                Seção 1:
                - Item 1
                - Item 2
                
                Seção 2:
                Algum texto de exemplo para testar a funcionalidade.
                """
                temp.write(content.encode('utf-8'))
                test_file = temp.name
                
            print(f"✅ Arquivo de teste criado: {test_file}")
        else:
            print(f"\n===== USANDO ARQUIVO EXISTENTE: {test_file} =====")
        
        # Verificar se o arquivo existe
        if not os.path.exists(test_file):
            print(f"❌ ERRO: O arquivo de teste não existe: {test_file}")
            return
        
        file_size = os.path.getsize(test_file)
        print(f"Verificação do arquivo: existe=True, tamanho={file_size} bytes")
        
        if file_size == 0:
            print("⚠️ AVISO: Arquivo tem tamanho zero!")
        
        # Converter o documento
        print("\n===== CONVERTENDO DOCUMENTO =====")
        print(f"Chamando converter.convert({test_file})...")
        
        try:
            doc_result = converter.convert(test_file)
            print("✅ Conversão inicial bem-sucedida")
            
            # Obter o documento
            print("Obtendo propriedade document...")
            doc = doc_result.document
            print(f"✅ Documento obtido: {doc}")
            
            # Exportar para markdown
            print("\n===== EXPORTANDO PARA MARKDOWN =====")
            markdown = doc.export_to_markdown()
            print(f"✅ Markdown gerado com {len(markdown)} caracteres")
            print("\nPrimeiros 300 caracteres do markdown:")
            print("-" * 50)
            print(markdown[:300] + "..." if len(markdown) > 300 else markdown)
            print("-" * 50)
            
            # Verificar se há métodos adicionais disponíveis
            print("\n===== MÉTODOS DISPONÍVEIS NO DOCUMENTO =====")
            print(f"Métodos do documento: {dir(doc)}")
            
            print("\n✅ TESTE CONCLUÍDO COM SUCESSO")
            return True
            
        except Exception as e:
            print(f"❌ ERRO na conversão: {str(e)}")
            logger.error(f"Erro detalhado: {str(e)}", exc_info=True)
            return False
    
    except ImportError as e:
        print(f"❌ Erro de importação: {str(e)}")
        logger.error(f"Erro de importação: {str(e)}", exc_info=True)
        return False
    except Exception as e:
        print(f"❌ Erro geral: {str(e)}")
        logger.error(f"Erro geral: {str(e)}", exc_info=True)
        return False
    finally:
        # Limpar arquivo temporário se foi criado pelo teste
        if 'temp' in locals() and os.path.exists(test_file):
            try:
                os.unlink(test_file)
                print(f"✅ Arquivo temporário removido: {test_file}")
            except Exception as e:
                print(f"⚠️ Não foi possível remover o arquivo temporário: {str(e)}")

def main():
    """Função principal"""
    parser = argparse.ArgumentParser(description='Teste do DocumentConverter do docling')
    parser.add_argument('--file', '-f', help='Arquivo para testar a conversão')
    
    args = parser.parse_args()
    
    # Executar o teste
    test_document_converter(args.file)

if __name__ == "__main__":
    main() 