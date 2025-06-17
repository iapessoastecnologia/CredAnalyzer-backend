# CredAnalyzer - Backend

Backend do sistema CredAnalyzer para análise de documentos financeiros utilizando IA.

## Requisitos

- Python 3.9+
- Dependências listadas em requirements.txt

## Configuração

1. Clone o repositório
2. Instale as dependências:
```
pip install -r requirements.txt
```

3. Configure o arquivo .env na raiz do projeto:
```
OPENAI_API_KEY=sua_chave_da_openai
```

4. Configure o Firebase (opcional, mas necessário para salvar relatórios):
   - Crie um projeto no [Firebase Console](https://console.firebase.google.com/)
   - Vá em Configurações do Projeto > Contas de serviço > Firebase Admin SDK > Gerar nova chave privada
   - Salve o arquivo JSON gerado como `service-account.json` na raiz do projeto

   OU

   - Configure as credenciais como variável de ambiente:
   ```
   FIREBASE_CREDENTIALS={"type":"service_account",...} # Conteúdo completo do JSON
   FIREBASE_STORAGE_BUCKET=nome-do-bucket.appspot.com
   ```

## Execução

Para iniciar o servidor em modo de desenvolvimento:
```
python -m uvicorn app.main:app --reload
```

O servidor estará disponível em: http://localhost:8000

## Endpoints

- POST /analyze/ - Analisa documentos enviados
- POST /save_report/ - Salva relatório no Firebase
- GET /firebase_status/ - Verifica status da conexão com Firebase
- GET /health - Verifica status do serviço 