import os
from dotenv import load_dotenv
import stripe
import logging
import json
from datetime import datetime
from firebase_admin import firestore
from .firebase_service import get_firestore_db

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Carregar variáveis de ambiente
load_dotenv()

# Configurar Stripe com a chave secreta
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

# Definir preços dos planos
PLANOS = {
    "BASICO": {
        "name": "Plano Básico",
        "description": "20 relatórios",
        "price": 3500,  # em centavos (R$ 35,00)
        "reports": 20,
        "discount": 0
    },
    "INTERMEDIARIO": {
        "name": "Plano Intermediário",
        "description": "40 relatórios",
        "price": 5500,  # em centavos (R$ 55,00)
        "reports": 40,
        "discount": 22  # Desconto em porcentagem
    },
    "AVANCADO": {
        "name": "Plano Avançado",
        "description": "70 relatórios",
        "price": 7500,  # em centavos (R$ 75,00)
        "reports": 70,
        "discount": 46  # Desconto em porcentagem
    }
}

def init_stripe():
    """Verifica se a configuração do Stripe está correta"""
    try:
        if not stripe.api_key:
            logger.error("STRIPE_SECRET_KEY não definida nas variáveis de ambiente")
            return False
            
        # Teste básico para verificar a configuração
        stripe.Plan.list(limit=1)
        logger.info("Configuração do Stripe verificada com sucesso")
        return True
    except Exception as e:
        logger.error(f"Erro ao inicializar Stripe: {str(e)}")
        return False

def criar_cliente(user_id, email, nome):
    """
    Cria um cliente no Stripe e associa ao usuário no Firestore
    
    Args:
        user_id (str): ID do usuário no Firebase
        email (str): Email do usuário
        nome (str): Nome do usuário
        
    Returns:
        str: ID do cliente no Stripe ou None se falhar
    """
    try:
        # Verificar se o cliente já existe
        db = get_firestore_db()
        user_doc = db.collection('usuarios').document(user_id).get()
        
        if user_doc.exists:
            user_data = user_doc.to_dict()
            if user_data.get('stripeCustomerId'):
                logger.info(f"Cliente Stripe já existe para o usuário {user_id}")
                return user_data.get('stripeCustomerId')
        
        # Criar cliente no Stripe
        customer = stripe.Customer.create(
            email=email,
            name=nome,
            metadata={
                "firebase_user_id": user_id
            }
        )
        
        # Salvar ID do cliente no Firestore
        db.collection('usuarios').document(user_id).set({
            'stripeCustomerId': customer.id
        }, merge=True)
        
        logger.info(f"Cliente Stripe criado com sucesso: {customer.id}")
        return customer.id
        
    except Exception as e:
        logger.error(f"Erro ao criar cliente no Stripe: {str(e)}")
        return None

def criar_sessao_checkout(user_id, plano_id, customer_id=None):
    """
    Cria uma sessão de checkout para pagamento único
    
    Args:
        user_id (str): ID do usuário
        plano_id (str): ID do plano (BASICO, INTERMEDIARIO, AVANCADO)
        customer_id (str, optional): ID do cliente no Stripe
        
    Returns:
        dict: Informações da sessão ou erro
    """
    try:
        if plano_id not in PLANOS:
            return {"success": False, "error": "Plano inválido"}
            
        plano = PLANOS[plano_id]
        
        # Se não temos o customer_id, buscar do Firestore
        if not customer_id:
            db = get_firestore_db()
            user_doc = db.collection('usuarios').document(user_id).get()
            
            if user_doc.exists:
                user_data = user_doc.to_dict()
                customer_id = user_data.get('stripeCustomerId')
        
        # Criar sessão de checkout
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'brl',
                    'product_data': {
                        'name': plano['name'],
                        'description': plano['description'],
                    },
                    'unit_amount': plano['price'],
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url=os.getenv('FRONTEND_URL', 'http://localhost:3000') + '/pagamento/sucesso?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=os.getenv('FRONTEND_URL', 'http://localhost:3000') + '/pagamento/cancelado',
            customer=customer_id,
            metadata={
                'user_id': user_id,
                'plano_id': plano_id,
                'reports': plano['reports']
            }
        )
        
        return {
            "success": True,
            "session_id": checkout_session.id,
            "url": checkout_session.url
        }
        
    except Exception as e:
        logger.error(f"Erro ao criar sessão de checkout: {str(e)}")
        return {"success": False, "error": str(e)}

def criar_assinatura(user_id, plano_id, customer_id=None):
    """
    Cria um produto, preço e sessão de checkout para assinatura recorrente
    
    Args:
        user_id (str): ID do usuário
        plano_id (str): ID do plano (BASICO, INTERMEDIARIO, AVANCADO)
        customer_id (str, optional): ID do cliente no Stripe
        
    Returns:
        dict: Informações da sessão ou erro
    """
    try:
        if plano_id not in PLANOS:
            return {"success": False, "error": "Plano inválido"}
            
        plano = PLANOS[plano_id]
        
        # Se não temos o customer_id, buscar do Firestore
        if not customer_id:
            db = get_firestore_db()
            user_doc = db.collection('usuarios').document(user_id).get()
            
            if user_doc.exists:
                user_data = user_doc.to_dict()
                customer_id = user_data.get('stripeCustomerId')
        
        # Verificar se já existe um produto para o plano
        product_id = None
        produtos = stripe.Product.list(limit=100)
        
        for produto in produtos:
            if produto.name == f"{plano['name']} Mensal":
                product_id = produto.id
                break
        
        # Se não existe, criar o produto
        if not product_id:
            produto = stripe.Product.create(
                name=f"{plano['name']} Mensal",
                description=f"Assinatura mensal - {plano['description']}"
            )
            product_id = produto.id
        
        # Criar preço para o produto
        preco = stripe.Price.create(
            product=product_id,
            unit_amount=plano['price'],
            currency='brl',
            recurring={'interval': 'month'},
            nickname=f"{plano_id}-MENSAL"
        )
        
        # Criar sessão de checkout para assinatura
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price': preco.id,
                'quantity': 1,
            }],
            mode='subscription',
            success_url=os.getenv('FRONTEND_URL', 'http://localhost:3000') + '/pagamento/sucesso?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=os.getenv('FRONTEND_URL', 'http://localhost:3000') + '/pagamento/cancelado',
            customer=customer_id,
            metadata={
                'user_id': user_id,
                'plano_id': plano_id,
                'reports': plano['reports']
            }
        )
        
        return {
            "success": True,
            "session_id": checkout_session.id,
            "url": checkout_session.url
        }
        
    except Exception as e:
        logger.error(f"Erro ao criar assinatura: {str(e)}")
        return {"success": False, "error": str(e)}

def processar_webhook(payload, sig_header):
    """
    Processa webhooks enviados pelo Stripe
    
    Args:
        payload (bytes): Payload do webhook
        sig_header (str): Cabeçalho de assinatura
        
    Returns:
        dict: Resultado do processamento
    """
    endpoint_secret = os.getenv('STRIPE_WEBHOOK_SECRET')
    
    try:
        # Verificar assinatura se tivermos o segredo
        if endpoint_secret:
            try:
                event = stripe.Webhook.construct_event(
                    payload, sig_header, endpoint_secret
                )
            except ValueError as e:
                # Payload inválido
                logger.error(f"Payload inválido: {str(e)}")
                return {"success": False, "error": "Payload inválido"}
            except stripe.error.SignatureVerificationError as e:
                # Assinatura inválida
                logger.error(f"Assinatura inválida: {str(e)}")
                return {"success": False, "error": "Assinatura inválida"}
        else:
            # Se não temos o segredo, confiamos no payload
            try:
                event = json.loads(payload)
            except json.JSONDecodeError:
                logger.error("Payload não é um JSON válido")
                return {"success": False, "error": "Payload inválido"}
        
        logger.info(f"Evento Stripe recebido: {event['type']}")
        
        # Processar eventos específicos
        if event['type'] == 'checkout.session.completed':
            session = event['data']['object']
            
            # Extrair informações do metadata
            user_id = session['metadata'].get('user_id')
            plano_id = session['metadata'].get('plano_id')
            reports = int(session['metadata'].get('reports', 0))
            
            if not user_id or not plano_id or not reports:
                logger.error("Metadata incompleta na sessão de checkout")
                return {"success": False, "error": "Metadata incompleta"}
            
            # Atualizar subscription no Firestore
            db = get_firestore_db()
            
            # Verificar se é assinatura ou pagamento único
            if session['mode'] == 'subscription':
                # Assinatura
                subscription_id = session['subscription']
                subscription = stripe.Subscription.retrieve(subscription_id)
                
                # Verificar créditos atuais do usuário, se houver
                user_data = db.collection('usuarios').document(user_id).get().to_dict() or {}
                subscription_atual = user_data.get('subscription', {})
                reports_atuais = subscription_atual.get('reportsLeft', 0)
                
                # Estrutura antiga (mantida para compatibilidade)
                db.collection('usuarios').document(user_id).set({
                    'subscription': {
                        'planName': PLANOS[plano_id]['name'],
                        'creditosPlano': reports,  # Novo campo para armazenar os créditos fixos do plano
                        'reportsLeft': reports_atuais + reports,  # Somar créditos novos com os restantes
                        'startDate': firestore.SERVER_TIMESTAMP,
                        'endDate': datetime.fromtimestamp(subscription.current_period_end),
                        'autoRenew': True,
                        'stripeSubscriptionId': subscription_id
                    }
                }, merge=True)
                
                # Nova estrutura na coleção pagamentos
                payment_data = {
                    "subscription": {
                        "autoRenew": True,
                        "endDate": datetime.fromtimestamp(subscription.current_period_end),
                        "paymentInfo": {
                            "amount": session['amount_total'] / 100.0,
                            "lastPaymentDate": datetime.now(),
                            "paymentId": session['payment_intent'],
                            "paymentMethod": "card",
                            "planId": plano_id,
                            "planName": PLANOS[plano_id]['name']
                        },
                        "creditosPlano": reports,  # Novo campo para armazenar os créditos fixos do plano
                        "reportsLeft": reports_atuais + reports,  # Somar créditos novos com os restantes
                        "startDate": datetime.now()
                    },
                    "temPlano": True,
                    "userId": user_id
                }
                
                # Salvar na coleção "pagamentos"
                pagamento_ref = db.collection('pagamentos').document()
                pagamento_ref.set(payment_data)
                
                # Atualizar o documento do usuário com a referência ao pagamento
                db.collection('usuarios').document(user_id).set({
                    'pagamentos': {
                        pagamento_ref.id: {
                            'data': datetime.now()
                        }
                    }
                }, merge=True)
                
                # Registrar pagamento no histórico (mantido para compatibilidade)
                db.collection('pagamentos_historico').add({
                    'usuarioId': user_id,
                    'planName': PLANOS[plano_id]['name'],
                    'amount': session['amount_total'],
                    'paymentMethod': 'card',
                    'timestamp': firestore.SERVER_TIMESTAMP,
                    'status': 'completed',
                    'stripePaymentId': session['payment_intent'],
                    'tipo': 'assinatura'
                })
                
            else:
                # Pagamento único
                # Verificar créditos atuais do usuário, se houver
                user_data = db.collection('usuarios').document(user_id).get().to_dict() or {}
                subscription_atual = user_data.get('subscription', {})
                reports_atuais = subscription_atual.get('reportsLeft', 0)
                
                # Estrutura antiga (mantida para compatibilidade)
                db.collection('usuarios').document(user_id).set({
                    'subscription': {
                        'planName': PLANOS[plano_id]['name'],
                        'creditosPlano': reports,  # Novo campo para armazenar os créditos fixos do plano
                        'reportsLeft': reports_atuais + reports,  # Somar créditos novos com os restantes
                        'startDate': firestore.SERVER_TIMESTAMP,
                        'autoRenew': False
                    }
                }, merge=True)
                
                # Nova estrutura na coleção pagamentos
                payment_data = {
                    "subscription": {
                        "autoRenew": False,
                        "paymentInfo": {
                            "amount": session['amount_total'] / 100.0,
                            "lastPaymentDate": datetime.now(),
                            "paymentId": session['payment_intent'],
                            "paymentMethod": "card",
                            "planId": plano_id,
                            "planName": PLANOS[plano_id]['name']
                        },
                        "creditosPlano": reports,  # Novo campo para armazenar os créditos fixos do plano
                        "reportsLeft": reports_atuais + reports,  # Somar créditos novos com os restantes
                        "startDate": datetime.now()
                    },
                    "temPlano": True,
                    "userId": user_id
                }
                
                # Salvar na coleção "pagamentos"
                pagamento_ref = db.collection('pagamentos').document()
                pagamento_ref.set(payment_data)
                
                # Atualizar o documento do usuário com a referência ao pagamento
                db.collection('usuarios').document(user_id).set({
                    'pagamentos': {
                        pagamento_ref.id: {
                            'data': datetime.now()
                        }
                    }
                }, merge=True)
                
                # Registrar pagamento no histórico (mantido para compatibilidade)
                db.collection('pagamentos_historico').add({
                    'usuarioId': user_id,
                    'planName': PLANOS[plano_id]['name'],
                    'amount': session['amount_total'],
                    'paymentMethod': 'card',
                    'timestamp': firestore.SERVER_TIMESTAMP,
                    'status': 'completed',
                    'stripePaymentId': session['payment_intent'],
                    'tipo': 'pagamento_unico'
                })
                
            logger.info(f"Pagamento processado com sucesso para o usuário {user_id}")
            return {"success": True}
            
        elif event['type'] == 'invoice.payment_succeeded':
            # Renovação de assinatura
            invoice = event['data']['object']
            subscription_id = invoice['subscription']
            
            if not subscription_id:
                return {"success": False, "error": "ID de assinatura não encontrado"}
                
            # Buscar assinatura
            subscription = stripe.Subscription.retrieve(subscription_id)
            
            # Buscar usuário pelo customer_id
            db = get_firestore_db()
            usuarios_ref = db.collection('usuarios')
            query = usuarios_ref.where('stripeCustomerId', '==', invoice['customer'])
            usuarios = query.get()
            
            if not usuarios:
                logger.error(f"Usuário não encontrado para customer_id {invoice['customer']}")
                return {"success": False, "error": "Usuário não encontrado"}
                
            user_doc = usuarios[0]
            user_id = user_doc.id
            user_data = user_doc.to_dict()
            
            # Extrair plano do usuário
            plano_atual = user_data.get('subscription', {}).get('planName')
            plano_id = None
            
            # Encontrar plano_id pelo nome
            for key, plano in PLANOS.items():
                if plano['name'] == plano_atual:
                    plano_id = key
                    break
                    
            if not plano_id:
                logger.error(f"Plano não identificado para o usuário {user_id}")
                return {"success": False, "error": "Plano não identificado"}
            
            # Verificar créditos atuais do usuário
            subscription_atual = user_data.get('subscription', {})
            reports_atuais = subscription_atual.get('reportsLeft', 0)
            reports_do_plano = PLANOS[plano_id]['reports']
                
            # Estrutura antiga (mantida para compatibilidade)
            db.collection('usuarios').document(user_id).set({
                'subscription': {
                    'planName': PLANOS[plano_id]['name'],
                    'creditosPlano': reports_do_plano,  # Novo campo para armazenar os créditos fixos do plano
                    'reportsLeft': reports_atuais + reports_do_plano,  # Somar créditos novos com os restantes
                    'startDate': firestore.SERVER_TIMESTAMP,
                    'endDate': datetime.fromtimestamp(subscription.current_period_end),
                    'autoRenew': True,
                    'stripeSubscriptionId': subscription_id
                }
            }, merge=True)
            
            # Nova estrutura na coleção pagamentos
            payment_data = {
                "subscription": {
                    "autoRenew": True,
                    "endDate": datetime.fromtimestamp(subscription.current_period_end),
                    "paymentInfo": {
                        "amount": invoice['amount_paid'] / 100.0,
                        "lastPaymentDate": datetime.now(),
                        "paymentId": invoice['payment_intent'],
                        "paymentMethod": "card",
                        "planId": plano_id,
                        "planName": PLANOS[plano_id]['name']
                    },
                    "creditosPlano": reports_do_plano,  # Novo campo para armazenar os créditos fixos do plano
                    "reportsLeft": reports_atuais + reports_do_plano,  # Somar créditos novos com os restantes
                    "startDate": datetime.now()
                },
                "temPlano": True,
                "userId": user_id
            }
            
            # Salvar na coleção "pagamentos"
            pagamento_ref = db.collection('pagamentos').document()
            pagamento_ref.set(payment_data)
            
            # Atualizar o documento do usuário com a referência ao pagamento
            db.collection('usuarios').document(user_id).set({
                'pagamentos': {
                    pagamento_ref.id: {
                        'data': datetime.now()
                    }
                }
            }, merge=True)
            
            # Registrar pagamento no histórico (mantido para compatibilidade)
            db.collection('pagamentos_historico').add({
                'usuarioId': user_id,
                'planName': PLANOS[plano_id]['name'],
                'amount': invoice['amount_paid'],
                'paymentMethod': 'card',
                'timestamp': firestore.SERVER_TIMESTAMP,
                'status': 'completed',
                'stripePaymentId': invoice['payment_intent'],
                'tipo': 'renovacao_assinatura'
            })
            
            logger.info(f"Assinatura renovada com sucesso para o usuário {user_id}")
            return {"success": True}
            
        # Outros eventos que podemos processar:
        elif event['type'] == 'customer.subscription.deleted':
            subscription = event['data']['object']
            
            # Buscar usuário pelo customer_id
            db = get_firestore_db()
            usuarios_ref = db.collection('usuarios')
            query = usuarios_ref.where('stripeCustomerId', '==', subscription['customer'])
            usuarios = query.get()
            
            if not usuarios:
                logger.error(f"Usuário não encontrado para customer_id {subscription['customer']}")
                return {"success": False, "error": "Usuário não encontrado"}
                
            user_doc = usuarios[0]
            user_id = user_doc.id
            
            # Atualizar assinatura do usuário como cancelada
            db.collection('usuarios').document(user_id).set({
                'subscription': {
                    'autoRenew': False,
                    'canceledAt': firestore.SERVER_TIMESTAMP
                }
            }, merge=True)
            
            logger.info(f"Assinatura cancelada para o usuário {user_id}")
            return {"success": True}
            
        logger.info(f"Evento do Stripe processado: {event['type']}")
        return {"success": True}
        
    except Exception as e:
        logger.error(f"Erro ao processar webhook: {str(e)}")
        return {"success": False, "error": str(e)}

def listar_cartoes(customer_id):
    """
    Lista os cartões salvos de um cliente
    
    Args:
        customer_id (str): ID do cliente no Stripe
        
    Returns:
        list: Lista de cartões ou erro
    """
    try:
        payment_methods = stripe.PaymentMethod.list(
            customer=customer_id,
            type='card'
        )
        
        cartoes = []
        for pm in payment_methods:
            cartao = {
                'id': pm.id,
                'brand': pm.card.brand,
                'last4': pm.card.last4,
                'exp_month': pm.card.exp_month,
                'exp_year': pm.card.exp_year,
                'isDefault': False  # Será atualizado abaixo
            }
            cartoes.append(cartao)
        
        # Verificar cartão padrão
        customer = stripe.Customer.retrieve(customer_id)
        if customer.invoice_settings.default_payment_method:
            for cartao in cartoes:
                if cartao['id'] == customer.invoice_settings.default_payment_method:
                    cartao['isDefault'] = True
                    break
        
        return {"success": True, "cards": cartoes}
        
    except Exception as e:
        logger.error(f"Erro ao listar cartões: {str(e)}")
        return {"success": False, "error": str(e)}

def adicionar_cartao(customer_id, payment_method_id, set_default=False):
    """
    Adiciona um cartão ao cliente
    
    Args:
        customer_id (str): ID do cliente no Stripe
        payment_method_id (str): ID do método de pagamento (cartão)
        set_default (bool): Definir como cartão padrão
        
    Returns:
        dict: Resultado da operação
    """
    try:
        # Associar método de pagamento ao cliente
        stripe.PaymentMethod.attach(
            payment_method_id,
            customer=customer_id
        )
        
        # Se for o cartão padrão, definir
        if set_default:
            stripe.Customer.modify(
                customer_id,
                invoice_settings={
                    'default_payment_method': payment_method_id
                }
            )
        
        # Buscar detalhes do cartão
        payment_method = stripe.PaymentMethod.retrieve(payment_method_id)
        
        # Salvar no Firestore
        db = get_firestore_db()
        
        # Buscar usuário pelo customer_id
        usuarios_ref = db.collection('usuarios')
        query = usuarios_ref.where('stripeCustomerId', '==', customer_id)
        usuarios = query.get()
        
        if not usuarios:
            logger.error(f"Usuário não encontrado para customer_id {customer_id}")
            return {"success": False, "error": "Usuário não encontrado"}
            
        user_doc = usuarios[0]
        user_id = user_doc.id
        
        # Adicionar cartão ao Firestore
        db.collection('cartoes').add({
            'usuarioId': user_id,
            'lastFourDigits': payment_method.card.last4,
            'brand': payment_method.card.brand,
            'expiryDate': f"{payment_method.card.exp_month}/{payment_method.card.exp_year}",
            'isDefault': set_default,
            'stripePaymentMethodId': payment_method_id
        })
        
        return {
            "success": True, 
            "card": {
                'id': payment_method.id,
                'brand': payment_method.card.brand,
                'last4': payment_method.card.last4,
                'exp_month': payment_method.card.exp_month,
                'exp_year': payment_method.card.exp_year,
                'isDefault': set_default
            }
        }
        
    except Exception as e:
        logger.error(f"Erro ao adicionar cartão: {str(e)}")
        return {"success": False, "error": str(e)}

def remover_cartao(customer_id, payment_method_id):
    """
    Remove um cartão do cliente
    
    Args:
        customer_id (str): ID do cliente no Stripe
        payment_method_id (str): ID do método de pagamento (cartão)
        
    Returns:
        dict: Resultado da operação
    """
    try:
        # Verificar se é o cartão padrão
        customer = stripe.Customer.retrieve(customer_id)
        is_default = (customer.invoice_settings.default_payment_method == payment_method_id)
        
        # Desassociar método de pagamento do cliente
        stripe.PaymentMethod.detach(payment_method_id)
        
        # Remover do Firestore
        db = get_firestore_db()
        cartoes_ref = db.collection('cartoes')
        query = cartoes_ref.where('stripePaymentMethodId', '==', payment_method_id)
        cartoes = query.get()
        
        for cartao in cartoes:
            cartao.reference.delete()
        
        # Se era o cartão padrão, precisamos configurar outro
        if is_default:
            # Buscar outro cartão disponível
            payment_methods = stripe.PaymentMethod.list(
                customer=customer_id,
                type='card',
                limit=1
            )
            
            if payment_methods.data:
                new_default = payment_methods.data[0].id
                
                # Definir como padrão
                stripe.Customer.modify(
                    customer_id,
                    invoice_settings={
                        'default_payment_method': new_default
                    }
                )
                
                # Atualizar no Firestore
                query = cartoes_ref.where('stripePaymentMethodId', '==', new_default)
                cartoes = query.get()
                
                for cartao in cartoes:
                    cartao.reference.update({'isDefault': True})
        
        return {"success": True}
        
    except Exception as e:
        logger.error(f"Erro ao remover cartão: {str(e)}")
        return {"success": False, "error": str(e)}

def atualizar_cartao_padrao(customer_id, payment_method_id):
    """
    Define um cartão como padrão
    
    Args:
        customer_id (str): ID do cliente no Stripe
        payment_method_id (str): ID do método de pagamento (cartão)
        
    Returns:
        dict: Resultado da operação
    """
    try:
        # Definir cartão como padrão no Stripe
        stripe.Customer.modify(
            customer_id,
            invoice_settings={
                'default_payment_method': payment_method_id
            }
        )
        
        # Atualizar no Firestore
        db = get_firestore_db()
        cartoes_ref = db.collection('cartoes')
        
        # Primeiro remover o status de padrão dos outros cartões
        query = cartoes_ref.where('isDefault', '==', True)
        cartoes = query.get()
        
        for cartao in cartoes:
            cartao.reference.update({'isDefault': False})
        
        # Definir o novo padrão
        query = cartoes_ref.where('stripePaymentMethodId', '==', payment_method_id)
        cartoes = query.get()
        
        for cartao in cartoes:
            cartao.reference.update({'isDefault': True})
        
        return {"success": True}
        
    except Exception as e:
        logger.error(f"Erro ao atualizar cartão padrão: {str(e)}")
        return {"success": False, "error": str(e)}

def consumir_relatorio(user_id):
    """
    Reduz o contador de relatórios disponíveis para o usuário
    
    Args:
        user_id (str): ID do usuário
        
    Returns:
        dict: Resultado da operação ou erro
    """
    try:
        db = get_firestore_db()
        user_ref = db.collection('usuarios').document(user_id)
        user_doc = user_ref.get()
        
        if not user_doc.exists:
            return {"success": False, "error": "Usuário não encontrado"}
            
        user_data = user_doc.to_dict()
        subscription = user_data.get('subscription', {})
        reports_left = subscription.get('reportsLeft', 0)
        
        if reports_left <= 0:
            return {"success": False, "error": "Não há relatórios disponíveis"}
        
        # Atualizar contador de relatórios
        user_ref.update({
            'subscription.reportsLeft': reports_left - 1
        })
        
        return {
            "success": True, 
            "reports_left": reports_left - 1
        }
        
    except Exception as e:
        logger.error(f"Erro ao consumir relatório: {str(e)}")
        return {"success": False, "error": str(e)}

def obter_historico_pagamentos(user_id):
    """
    Obtém o histórico de pagamentos do usuário
    
    Args:
        user_id (str): ID do usuário
        
    Returns:
        dict: Lista de pagamentos ou erro
    """
    try:
        db = get_firestore_db()
        pagamentos_ref = db.collection('pagamentos_historico')
        query = pagamentos_ref.where('usuarioId', '==', user_id)
        pagamentos = query.get()
        
        resultado = []
        for pagamento in pagamentos:
            dados = pagamento.to_dict()
            
            # Converter timestamp para ISO
            if dados.get('timestamp'):
                if hasattr(dados['timestamp'], 'timestamp'):
                    # Se for objeto Timestamp do Firestore
                    dados['timestamp'] = dados['timestamp'].isoformat()
            
            resultado.append(dados)
            
        return {"success": True, "payments": resultado}
        
    except Exception as e:
        logger.error(f"Erro ao obter histórico de pagamentos: {str(e)}")
        return {"success": False, "error": str(e)}

def criar_pagamento_pix(user_id, plano_id, telefone=None):
    """
    Cria um pagamento via PIX
    
    Args:
        user_id (str): ID do usuário
        plano_id (str): ID do plano (BASICO, INTERMEDIARIO, AVANCADO)
        telefone (str, optional): Telefone do usuário
        
    Returns:
        dict: Informações do pagamento ou erro
    """
    try:
        if plano_id not in PLANOS:
            return {"success": False, "error": "Plano inválido"}
            
        plano = PLANOS[plano_id]
        
        # Gerar ID de pagamento mockado (em produção seria o ID do Stripe ou outra plataforma de pagamento)
        payment_id = f"mock_payment_{int(datetime.now().timestamp() * 1000)}"
        
        # Obter instância do Firestore
        db = get_firestore_db()
        
        # Criar dados do pagamento
        payment_data = {
            "subscription": {
                "autoRenew": True,
                "endDate": datetime.now().replace(year=datetime.now().year + 1),  # 1 ano de validade
                "paymentInfo": {
                    "amount": plano['price'] / 100.0,  # Converter de centavos para reais
                    "lastPaymentDate": datetime.now(),
                    "paymentId": payment_id,
                    "paymentMethod": "pix",
                    "planId": plano_id,
                    "planName": plano['name']
                },
                "reportsLeft": plano['reports'],
                "startDate": datetime.now()
            },
            "temPlano": True,
            "userId": user_id
        }
        
        if telefone:
            payment_data["telefone"] = telefone
        
        # Salvar na coleção "pagamentos"
        pagamento_ref = db.collection('pagamentos').document()
        pagamento_ref.set(payment_data)
        
        # Verificar créditos atuais do usuário, se houver
        user_data = db.collection('usuarios').document(user_id).get().to_dict() or {}
        subscription_atual = user_data.get('subscription', {})
        reports_atuais = subscription_atual.get('reportsLeft', 0)
        
        # Atualizar o documento do usuário
        db.collection('usuarios').document(user_id).set({
            'subscription': {
                'planName': plano['name'],
                'creditosPlano': plano['reports'],  # Novo campo para armazenar os créditos fixos do plano
                'reportsLeft': reports_atuais + plano['reports'],  # Somar créditos novos com os restantes
                'startDate': firestore.SERVER_TIMESTAMP,
                'endDate': payment_data["subscription"]["endDate"],
                'autoRenew': True
            },
            'pagamentos': {
                pagamento_ref.id: {
                    'data': datetime.now()
                }
            }
        }, merge=True)
        
        # Atualizar também na coleção pagamentos
        payment_data["subscription"]["creditosPlano"] = plano['reports']
        payment_data["subscription"]["reportsLeft"] = reports_atuais + plano['reports']
        pagamento_ref.set(payment_data)
        
        # Registrar pagamento no histórico (mantido para compatibilidade)
        db.collection('pagamentos_historico').add({
            'usuarioId': user_id,
            'planName': plano['name'],
            'amount': plano['price'],
            'paymentMethod': 'pix',
            'timestamp': firestore.SERVER_TIMESTAMP,
            'status': 'completed',
            'stripePaymentId': payment_id,
            'tipo': 'pagamento_pix'
        })
        
        return {
            "success": True,
            "payment_id": payment_id,
            "pagamento_ref": pagamento_ref.id,
            "plano": plano['name'],
            "valor": plano['price'] / 100.0,
            "reports": plano['reports']
        }
        
    except Exception as e:
        logger.error(f"Erro ao criar pagamento PIX: {str(e)}")
        return {"success": False, "error": str(e)} 