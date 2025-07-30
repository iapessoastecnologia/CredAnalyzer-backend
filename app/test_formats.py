"""
Teste para verificar os formatos suportados pelo DocumentConverter.
"""
import tempfile
import os
from docling.document_converter import DocumentConverter

def test_formats():
    """Verifica os formatos suportados pelo DocumentConverter."""
    print("===== VERIFICANDO FORMATOS SUPORTADOS =====")
    converter = DocumentConverter()
    
    print("Formatos permitidos:")
    for fmt in converter.allowed_formats:
        print(f"- {fmt.value}")
    
    print("\n===== CRIANDO PDF DE TESTE =====")
    # Criar um PDF simples para teste
    pdf_content = b"""%PDF-1.5
1 0 obj
<</Type/Catalog/Pages 2 0 R>>
endobj
2 0 obj
<</Type/Pages/Kids[3 0 R]/Count 1>>
endobj
3 0 obj
<</Type/Page/MediaBox[0 0 595 842]/Parent 2 0 R/Resources<<>>>>
endobj
xref
0 4
0000000000 65535 f 
0000000010 00000 n 
0000000053 00000 n 
0000000102 00000 n 
trailer
<</Size 4/Root 1 0 R>>
startxref
176
%%EOF
"""
    
    # Salvar o PDF de teste
    pdf_path = "test_document.pdf"
    with open(pdf_path, "wb") as f:
        f.write(pdf_content)
    
    print(f"PDF criado em: {pdf_path}")
    print(f"Tamanho: {os.path.getsize(pdf_path)} bytes")
    
    # Tentar converter o PDF
    print("\n===== TENTANDO CONVERTER PDF =====")
    try:
        print(f"Chamando converter.convert({pdf_path})...")
        result = converter.convert(pdf_path)
        print("✅ Conversão bem-sucedida!")
        
        print("\nObtendo documento...")
        doc = result.document
        print(f"✅ Documento obtido: {doc}")
        
        print("\nExportando para markdown...")
        markdown = doc.export_to_markdown()
        print(f"✅ Markdown gerado com {len(markdown)} caracteres")
        
        if markdown:
            print("\nConteúdo do markdown:")
            print("-" * 50)
            print(markdown)
            print("-" * 50)
        
    except Exception as e:
        print(f"❌ Erro na conversão: {str(e)}")
    
    finally:
        # Limpar o arquivo de teste
        try:
            os.remove(pdf_path)
            print(f"\n✅ Arquivo de teste removido: {pdf_path}")
        except:
            print(f"\n⚠️ Não foi possível remover o arquivo de teste: {pdf_path}")

if __name__ == "__main__":
    test_formats() 