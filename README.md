# CredAnalyzer - Backend

Backend para a aplicação CredAnalyzer, responsável por analisar documentos e gerar relatórios de análise de crédito.

## Requisitos

- Python 3.8+
- Recomenda-se o uso de ambiente virtual (venv)

## Instalação

1. Clone o repositório:
```
git clone <url-do-repositorio>
```

2. Crie e ative um ambiente virtual:
```
python -m venv venv
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows
```

3. Instale as dependências:
```
pip install -r requirements.txt
```

4. Configure as variáveis de ambiente criando um arquivo `.env` na raiz do projeto:
```
OPENAI_API_KEY=sua_chave_da_openai
FIREBASE_CREDENTIALS="{...}"  # ou configure as credenciais separadamente
STRIPE_SECRET_KEY=sua_chave_secreta_do_stripe
STRIPE_PUBLISHABLE_KEY=sua_chave_publicavel_do_stripe
STRIPE_WEBHOOK_SECRET=seu_segredo_de_webhook_do_stripe
FRONTEND_URL=http://localhost:3000
```

## Execução

```
uvicorn app.main:app --reload
```

A API estará disponível em http://localhost:8000

## Documentação da API

Acesse http://localhost:8000/docs para visualizar a documentação interativa da API.

## Integração com Stripe

### Configuração

1. Crie uma conta na [Stripe](https://stripe.com/)
2. Obtenha suas chaves de API (pública e secreta) no [Dashboard da Stripe](https://dashboard.stripe.com/apikeys)
3. Configure um webhook para receber eventos da Stripe
4. Adicione as chaves no arquivo `.env`

### Endpoints Disponíveis

#### Gerenciamento de Clientes
- `POST /stripe/cliente/`: Cria um cliente no Stripe associado a um usuário

#### Pagamentos
- `POST /stripe/checkout/pagamento/`: Cria uma sessão de checkout para pagamento único
- `POST /stripe/checkout/assinatura/`: Cria uma sessão de checkout para assinatura recorrente
- `POST /stripe/webhook/`: Endpoint para receber webhooks da Stripe

#### Gerenciamento de Cartões
- `GET /stripe/cartoes/{customer_id}`: Lista os cartões de um cliente
- `POST /stripe/cartoes/`: Adiciona um cartão ao cliente
- `DELETE /stripe/cartoes/{customer_id}/{payment_method_id}`: Remove um cartão
- `PUT /stripe/cartoes/{customer_id}/{payment_method_id}/padrao`: Define um cartão como padrão

#### Gestão de Assinaturas
- `POST /stripe/consumir_relatorio/{user_id}`: Consome um relatório do plano do usuário
- `GET /stripe/pagamentos/{user_id}`: Obtém o histórico de pagamentos do usuário
- `POST /pagamentos/`: Salva informações de pagamento no banco de dados
- `POST /pagamento/pix/`: Cria um pagamento via PIX

### Planos Disponíveis

- **Plano Básico**: 20 relatórios por R$ 35,00
- **Plano Intermediário**: 40 relatórios por R$ 55,00 (22% de desconto)
- **Plano Avançado**: 70 relatórios por R$ 75,00 (46% de desconto)

### Fluxo de Dados

1. O frontend coleta dados do cartão via Stripe Elements
2. O frontend envia token para o backend Python
3. O backend processa o pagamento com API do Stripe
4. O backend atualiza o Firestore após confirmação
5. O frontend escuta mudanças no Firestore para atualizar a UI

### Segurança

- Dados de cartão nunca são armazenados diretamente no aplicativo
- A validação e processamento do pagamento é feito pelo Stripe
- Apenas tokens e IDs de referência são armazenados no Firestore
- Todas as operações sensíveis são processadas pelo backend

## Estrutura do Banco de Dados (Firestore)

### Coleções

#### usuarios
```
usuarios/
   {userId}/
     subscription: {
       planName: string,
       reportsLeft: number,
       startDate: timestamp,
       endDate: timestamp,
       autoRenew: boolean,
       stripeCustomerId: string,
       stripeSubscriptionId: string (opcional)
     }
```

#### pagamentos
```
pagamentos/
   {paymentId}/
     userId: string,
     temPlano: boolean,
     telefone: string (opcional),
     subscription: {
       autoRenew: boolean,
       endDate: timestamp,
       paymentInfo: {
         amount: number,
         lastPaymentDate: timestamp,
         paymentId: string,
         paymentMethod: string,
         planId: string,
         planName: string
       },
       reportsLeft: number,
       startDate: timestamp
     }
```

#### pagamentos_historico (mantido para compatibilidade)
```
pagamentos_historico/
   {paymentId}/
     usuarioId: string,
     planName: string,
     amount: number,
     paymentMethod: string,
     timestamp: timestamp,
     status: string,
     stripePaymentId: string,
     tipo: string (assinatura, pagamento_unico, renovacao_assinatura, pagamento_pix)
```

#### cartoes
```
cartoes/
   {cardId}/
     usuarioId: string,
     lastFourDigits: string,
     brand: string,
     expiryDate: string,
     isDefault: boolean,
     stripePaymentMethodId: string
```

## Endpoints

- POST /analyze/ - Analisa documentos enviados
- POST /save_report/ - Salva relatório no Firebase
- GET /firebase_status/ - Verifica status da conexão com Firebase
- GET /health - Verifica status do serviço 