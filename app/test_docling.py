"""
Arquivo de teste para verificar a funcionalidade do docling.
"""
import logging
import sys
import argparse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_docling():
    try:
        import docling
        logger.info("DocLing importado com sucesso")
        
        # Verificar se process_text existe
        if hasattr(docling, 'process_text'):
            logger.info("Função process_text encontrada")
            
            # Teste simples
            print("\n===== TESTE SIMPLES =====")
            texto_simples = "Este é um texto de teste para verificar o docling."
            print(f"ORIGINAL: {texto_simples}")
            resultado_simples = docling.process_text(texto_simples)
            print(f"PROCESSADO: {resultado_simples}")
            
            # Teste com texto de registro
            print("\n===== TESTE COM TEXTO DE REGISTRO =====")
            texto_registro = """INSTRUMENTO PARTICULAR DE CONTRATO SOCIAL
            
CONTRATANTE: JOÃO DA SILVA, brasileiro, solteiro, empresário, portador do CPF nº 123.456.789-00 e RG nº 1.234.567 SSP/SP, residente e domiciliado à Rua das Flores, 123, São Paulo/SP, CEP 01234-567.

CONTRATADO: EMPRESA XYZ LTDA., pessoa jurídica de direito privado, inscrita no CNPJ sob o nº 12.345.678/0001-90, com sede à Avenida Principal, 456, São Paulo/SP, CEP 01234-567, neste ato representada por seu sócio administrador JOSÉ PEREIRA, brasileiro, casado, empresário, portador do CPF nº 987.654.321-00.

Pelo presente instrumento particular, as partes acima qualificadas resolvem constituir uma sociedade empresária limitada, mediante as seguintes cláusulas e condições:

CLÁUSULA PRIMEIRA - DO NOME EMPRESARIAL
A sociedade girará sob o nome empresarial "EXEMPLO SOCIEDADE LTDA." e terá sede e domicílio na Rua Comercial, 789, São Paulo/SP, CEP 01234-567.

CLÁUSULA SEGUNDA - DO CAPITAL SOCIAL
O capital social será de R$ 100.000,00 (cem mil reais), divididos em 100.000 (cem mil) quotas no valor nominal de R$ 1,00 (um real) cada uma, distribuídas da seguinte forma:
a) JOÃO DA SILVA subscreve 60.000 (sessenta mil) quotas no valor de R$ 60.000,00 (sessenta mil reais);
b) EMPRESA XYZ LTDA. subscreve 40.000 (quarenta mil) quotas no valor de R$ 40.000,00 (quarenta mil reais).
"""
            print(f"ORIGINAL (primeiros 200 caracteres): {texto_registro[:200]}...")
            resultado_registro = docling.process_text(texto_registro)
            print(f"PROCESSADO (primeiros 500 caracteres): {resultado_registro[:500]}...")
            
            # Verificar se o resultado inclui markdown
            markdown_indicators = ["# ", "## ", "### ", "- ", "* ", "1. ", "> ", "```", "**", "_", "[", "]("]
            has_markdown = any(indicator in resultado_registro for indicator in markdown_indicators)
            
            print(f"\nO resultado contém formatação markdown? {'Sim' if has_markdown else 'Não'}")
            
            if has_markdown:
                print("Elementos markdown encontrados:")
                for indicator in markdown_indicators:
                    if indicator in resultado_registro:
                        print(f"- {indicator}")
            
            # Teste com texto de CNPJ
            print("\n===== TESTE COM TEXTO DE CNPJ =====")
            texto_cnpj = """REPÚBLICA FEDERATIVA DO BRASIL
CADASTRO NACIONAL DA PESSOA JURÍDICA - CNPJ

NÚMERO DE INSCRIÇÃO:
12.345.678/0001-90
DATA DE ABERTURA:
01/01/2020

NOME EMPRESARIAL:
EXEMPLO SOCIEDADE LTDA.

TÍTULO DO ESTABELECIMENTO (NOME FANTASIA):
EXEMPLO

CÓDIGO E DESCRIÇÃO DA ATIVIDADE ECONÔMICA PRINCIPAL:
47.51-2-01 - Comércio varejista especializado de equipamentos e suprimentos de informática
"""
            print(f"ORIGINAL: {texto_cnpj}")
            resultado_cnpj = docling.process_text(texto_cnpj)
            print(f"PROCESSADO: {resultado_cnpj}")
            
            # Teste com texto numérico/tabular
            print("\n===== TESTE COM TEXTO NUMÉRICO/TABULAR =====")
            texto_tabular = """DEMONSTRATIVO FINANCEIRO
Período: 01/01/2023 a 31/12/2023

RECEITAS:
Vendas Brutas         | R$ 500.000,00
(-) Impostos          | R$ 100.000,00
(=) Receita Líquida   | R$ 400.000,00

DESPESAS:
Administrativas       | R$ 150.000,00
Operacionais          | R$ 100.000,00
Financeiras           | R$  30.000,00
Total de Despesas     | R$ 280.000,00

RESULTADO:
Lucro Líquido         | R$ 120.000,00
"""
            print(f"ORIGINAL: {texto_tabular}")
            resultado_tabular = docling.process_text(texto_tabular)
            print(f"PROCESSADO: {resultado_tabular}")
            
            # Exibir informações sobre o processamento
            print("\n===== INFORMAÇÕES SOBRE O PROCESSAMENTO =====")
            if hasattr(docling, 'get_info'):
                info = docling.get_info()
                print(f"Informações do módulo: {info}")
            else:
                print("Função get_info não encontrada. Exibindo atributos disponíveis:")
                print(dir(docling))
            
        else:
            logger.error("Função process_text não encontrada no módulo docling")
            
            # Verificar quais funções estão disponíveis
            logger.info(f"Funções disponíveis em docling: {dir(docling)}")
    
    except ImportError:
        logger.error("Não foi possível importar docling. Verifique a instalação.")
    
    except Exception as e:
        logger.error(f"Erro ao testar docling: {str(e)}")

def process_custom_text(text):
    """Processa um texto personalizado com o docling"""
    try:
        import docling
        print("\n===== PROCESSANDO TEXTO PERSONALIZADO =====")
        print(f"TEXTO ORIGINAL:\n{text}")
        
        resultado = docling.process_text(text)
        
        print("\n===== RESULTADO DO PROCESSAMENTO =====")
        print(resultado)
        
        # Verificar se o resultado inclui markdown
        markdown_indicators = ["# ", "## ", "### ", "- ", "* ", "1. ", "> ", "```", "**", "_", "[", "]("]
        has_markdown = any(indicator in resultado for indicator in markdown_indicators)
        
        print(f"\nO resultado contém formatação markdown? {'Sim' if has_markdown else 'Não'}")
        
        if has_markdown:
            print("Elementos markdown encontrados:")
            for indicator in markdown_indicators:
                if indicator in resultado:
                    print(f"- {indicator}")
        
    except ImportError:
        logger.error("Não foi possível importar docling. Verifique a instalação.")
    except Exception as e:
        logger.error(f"Erro ao processar texto: {str(e)}")

def main():
    """Função principal para executar os testes"""
    parser = argparse.ArgumentParser(description='Teste do módulo DocLing')
    parser.add_argument('--file', '-f', help='Arquivo de texto para processar')
    parser.add_argument('--text', '-t', help='Texto para processar diretamente')
    parser.add_argument('--test', action='store_true', help='Executar testes padrão')
    
    args = parser.parse_args()
    
    if args.file:
        try:
            with open(args.file, 'r', encoding='utf-8') as f:
                text = f.read()
            process_custom_text(text)
        except Exception as e:
            logger.error(f"Erro ao ler arquivo: {str(e)}")
    
    elif args.text:
        process_custom_text(args.text)
    
    elif args.test or not (args.file or args.text):
        test_docling()
    
    else:
        parser.print_help()

if __name__ == "__main__":
    main()