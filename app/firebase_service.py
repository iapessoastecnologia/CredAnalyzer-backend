import os
from dotenv import load_dotenv
import time
import logging
import datetime

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Carregar variáveis de ambiente
load_dotenv()

# Tentar importar o firebase_admin
try:
    import firebase_admin
    from firebase_admin import credentials, firestore
    firebase_admin_available = True
except ImportError as e:
    firebase_admin_available = False
    logger.error(f"Erro ao importar firebase_admin: {str(e)}")
    logger.error("As funcionalidades do Firebase não estarão disponíveis. Verifique se o pacote está instalado: pip install firebase-admin")

def initialize_firebase():
    """
    Inicializa o Firebase Admin SDK para uso no backend.
    Procura por credenciais no arquivo service-account.json, nas variáveis de ambiente
    ou nas variáveis de configuração separadas.
    """
    try:
        # Garantir que o firebase_admin está disponível
        if not firebase_admin_available:
            logger.error("Firebase não disponível")
            return False
            
        # Verificar se já está inicializado
        if firebase_admin._apps:
            logger.info("Firebase já está inicializado")
            return True
        
        # Método 1: Tentar localizar o arquivo de credenciais
        if os.path.exists('service-account.json'):
            cred = credentials.Certificate('service-account.json')
            firebase_admin.initialize_app(cred)
            logger.info("Firebase inicializado via service-account.json")
            return True
        elif os.path.exists('backend/service-account.json'):
            cred = credentials.Certificate('backend/service-account.json')
            firebase_admin.initialize_app(cred)
            logger.info("Firebase inicializado via backend/service-account.json")
            return True
        
        # Método 2: Verificar se temos as credenciais completas
        if os.getenv('FIREBASE_CREDENTIALS'):
            import json
            firebase_creds = json.loads(os.getenv('FIREBASE_CREDENTIALS'))
            cred = credentials.Certificate(firebase_creds)
            firebase_admin.initialize_app(cred)
            logger.info("Firebase inicializado via FIREBASE_CREDENTIALS")
            return True
        
        # Método 3: Verificar se temos variáveis separadas para inicializar com config padrão
        project_id = os.getenv('PROJECT_ID')
        api_key = os.getenv('API_KEY')
        if project_id and api_key:
            # Criar configuração do Firebase
            firebase_config = {
                "apiKey": api_key,
                "authDomain": os.getenv('AUTH_DOMAIN', f"{project_id}.firebaseapp.com"),
                "projectId": project_id,
                "storageBucket": os.getenv('STORAGE_BUCKET', f"{project_id}.appspot.com"),
                "messagingSenderId": os.getenv('MESSAGING_SENDER_ID', ""),
                "appId": os.getenv('APP_ID', ""),
                "measurementId": os.getenv('MEASUREMENT_ID', "")
            }
            
            # Inicializar sem credenciais de administrador (modo limitado)
            # Como não temos credenciais de admin, usamos um objeto vazio como credencial
            default_app = firebase_admin.initialize_app(name="default")
            logger.info(f"Firebase inicializado no modo config padrão para projeto: {project_id}")
            return True
            
        logger.warning("Nenhuma credencial do Firebase encontrada. Tentando modo anônimo.")
        # Tentar inicializar sem credenciais (para desenvolvimento/teste)
        default_app = firebase_admin.initialize_app()
        logger.info("Firebase inicializado no modo anônimo/padrão")
        return True
            
    except Exception as e:
        logger.error(f"Erro ao inicializar Firebase: {str(e)}")
        return False

# Simulador de Firestore para desenvolvimento quando admin SDK não estiver disponível
class FirestoreSimulator:
    def __init__(self):
        self.data = {}
        self.next_id = 1
        logger.info("Inicializando simulador de Firestore para desenvolvimento")
    
    def collection(self, collection_name):
        if collection_name not in self.data:
            self.data[collection_name] = {}
            
        simulator = self  # Referência para uso nas classes aninhadas
            
        class DocumentRef:
            def __init__(self, doc_id, collection_data):
                self.id = doc_id
                self.collection_data = collection_data
                
            def set(self, data):
                self.collection_data[self.id] = data
                logger.info(f"Simulador: Documento salvo em {collection_name}/{self.id}")
                return True
                
        class CollectionRef:
            def document(self, doc_id=None):
                if doc_id is None:
                    # Gerar ID automático
                    doc_id = f"auto_id_{simulator.next_id}"
                    simulator.next_id += 1
                    
                return DocumentRef(doc_id, simulator.data[collection_name])
                
            def where(self, field, op, value):
                # Simulação simplificada de consulta
                class QueryRef:
                    def get(self):
                        # Retorna documentos que correspondem ao filtro
                        class QuerySnapshot:
                            def __init__(self, docs):
                                self.docs = docs
                                
                        filtered_docs = []
                        for doc_id, doc_data in simulator.data[collection_name].items():
                            # Verifica se o campo existe
                            if field in doc_data:
                                # Simula operações básicas de comparação
                                if op == "==" and doc_data[field] == value:
                                    filtered_docs.append(self._create_doc_snapshot(doc_id, doc_data))
                                elif op == ">" and doc_data[field] > value:
                                    filtered_docs.append(self._create_doc_snapshot(doc_id, doc_data))
                                elif op == ">=" and doc_data[field] >= value:
                                    filtered_docs.append(self._create_doc_snapshot(doc_id, doc_data))
                                elif op == "<" and doc_data[field] < value:
                                    filtered_docs.append(self._create_doc_snapshot(doc_id, doc_data))
                                elif op == "<=" and doc_data[field] <= value:
                                    filtered_docs.append(self._create_doc_snapshot(doc_id, doc_data))
                                    
                        return QuerySnapshot(filtered_docs)
                        
                    def _create_doc_snapshot(self, doc_id, doc_data):
                        # Cria um snapshot de documento
                        class DocumentSnapshot:
                            def __init__(self, id, data):
                                self.id = id
                                self._data = data
                                
                            def to_dict(self):
                                return self._data
                                
                        return DocumentSnapshot(doc_id, doc_data)
                        
                return QueryRef()
                
        return CollectionRef()

# Variável global para o simulador
_firestore_simulator = None

# Obter instância do Firestore
def get_firestore_db():
    """Retorna uma instância do banco de dados Firestore ou simulador."""
    global _firestore_simulator
    
    if not firebase_admin_available:
        logger.warning("Firebase não disponível, usando simulador")
        if _firestore_simulator is None:
            _firestore_simulator = FirestoreSimulator()
        return _firestore_simulator
    
    if not firebase_admin._apps:
        if not initialize_firebase():
            logger.warning("Firebase não inicializado, usando simulador")
            if _firestore_simulator is None:
                _firestore_simulator = FirestoreSimulator()
            return _firestore_simulator
    
    try:
        return firestore.client()
    except Exception as e:
        logger.warning(f"Erro ao obter cliente Firestore: {str(e)}. Usando simulador.")
        if _firestore_simulator is None:
            _firestore_simulator = FirestoreSimulator()
        return _firestore_simulator

def save_report(user_id, user_name, planning_data, analysis_files=None, report_content=None):
    """
    Salva o relatório no Firestore sem usar o Storage.
    
    Args:
        user_id (str): ID do usuário
        user_name (str): Nome do usuário
        planning_data (dict): Dados do planejamento
        analysis_files (dict, optional): Arquivos de análise. 
        report_content (str, optional): Conteúdo do relatório em texto
    
    Returns:
        dict: Resultado da operação
    """
    try:
        # Verificar se o firebase_admin está disponível
        if not firebase_admin_available:
            logger.error("Módulo firebase_admin não encontrado")
            return {"success": False, "error": "Módulo firebase_admin não está disponível"}
            
        # Inicializar Firebase se necessário
        if not firebase_admin._apps:
            if not initialize_firebase():
                return {"success": False, "error": "Firebase não inicializado"}
        
        # Obter instância do Firestore
        db = get_firestore_db()
        if db is None:
            logger.error("Não foi possível obter instância do Firestore")
            return {"success": False, "error": "Falha ao acessar Firestore"}
        
        # Preparar informações sobre documentos enviados
        documentos_enviados = {}
        
        # Guardar metadados dos arquivos, sem fazer upload
        if analysis_files:
            for doc_type, file_content in analysis_files.items():
                if file_content:
                    # Mapeamento de nomes em português
                    nomes_documentos = {
                        "incomeTax": "Imposto de Renda",
                        "registration": "Registro",
                        "taxStatus": "Situação Fiscal",
                        "taxBilling": "Faturamento Fiscal",
                        "managementBilling": "Faturamento Gerencial",
                        "spcSerasa": "SPC e Serasa",
                        "statement": "Demonstrativo"
                    }
                    
                    # Se for binário, salvamos apenas a informação de que o arquivo foi recebido
                    doc_name = nomes_documentos.get(doc_type, doc_type)
                    documentos_enviados[doc_name] = {
                        "arquivo_recebido": True,
                        "timestamp": time.time()
                    }
                    
                    # Se tivermos metadados adicionais, incluí-los
                    if hasattr(file_content, 'filename'):
                        documentos_enviados[doc_name]['nome_arquivo'] = file_content.filename
                    if hasattr(file_content, 'content_type'):
                        documentos_enviados[doc_name]['tipo'] = file_content.content_type
        
        # Preparar dados de planejamento
        planejamento_inicial = {
            "segmentoEmpresa": planning_data.get("segment", ""),
            "objetivoCredito": planning_data.get("objective", ""),
            "valorCreditoBuscado": planning_data.get("creditAmount", 0),
            "tempoEmpresa": planning_data.get("timeInCompany", 0)
        }
        
        # Ajustar campos personalizados, se presentes
        if planning_data.get("segment") == "Outro" and planning_data.get("otherSegment"):
            planejamento_inicial["segmentoEmpresa"] = planning_data.get("otherSegment", "")
        
        if planning_data.get("objective") == "Outro" and planning_data.get("otherObjective"):
            planejamento_inicial["objetivoCredito"] = planning_data.get("otherObjective", "")
        
        # Criar documento no Firestore
        report_data = {
            "usuarioId": user_id,
            "nomeUsuario": user_name,
            "planejamentoInicial": planejamento_inicial,
            "documentosEnviados": documentos_enviados,
            "timestamp": firestore.SERVER_TIMESTAMP
        }
        
        # Adicionar conteúdo do relatório, se existir
        if report_content:
            report_data["conteudoRelatorio"] = report_content
        
        # Salvar no Firestore
        report_ref = db.collection("relatorios").document()
        report_ref.set(report_data)
        
        logger.info(f"Relatório salvo no Firestore com ID: {report_ref.id}")
        return {"success": True, "report_id": report_ref.id}
    except Exception as e:
        import traceback
        logger.error(f"Erro ao salvar relatório: {str(e)}")
        traceback.print_exc()
        return {"success": False, "error": str(e)}

def get_reports_by_date_range(user_id=None, start_date=None, end_date=None):
    """
    Busca relatórios no Firestore dentro de um intervalo de datas.
    
    Args:
        user_id (str, optional): ID do usuário para filtrar apenas seus relatórios
        start_date (datetime.date, optional): Data inicial do intervalo
        end_date (datetime.date, optional): Data final do intervalo
    
    Returns:
        dict: Relatórios encontrados ou mensagem de erro
    """
    try:
        # Verificar se o firebase_admin está disponível
        if not firebase_admin_available:
            logger.error("Módulo firebase_admin não encontrado")
            return {"success": False, "error": "Módulo firebase_admin não está disponível", "reports": []}
            
        # Inicializar Firebase se necessário
        if not firebase_admin._apps:
            if not initialize_firebase():
                return {"success": False, "error": "Firebase não inicializado", "reports": []}
        
        # Obter instância do Firestore
        db = get_firestore_db()
        if db is None:
            logger.error("Não foi possível obter instância do Firestore")
            return {"success": False, "error": "Falha ao acessar Firestore", "reports": []}
        
        # Definir datas padrão (hoje) se não forem especificadas
        if not start_date:
            start_date = datetime.datetime.now().date()
        if not end_date:
            end_date = datetime.datetime.now().date()
            
        # Converter para datetime com hora inicial e final do dia
        start_datetime = datetime.datetime.combine(start_date, datetime.time.min)
        end_datetime = datetime.datetime.combine(end_date, datetime.time.max)
        
        # Consulta base na coleção de relatórios
        query_ref = db.collection("relatorios")
        
        # Filtrar por usuário se especificado
        if user_id:
            query_ref = query_ref.where("usuarioId", "==", user_id)
        
        # Filtrar por intervalo de datas
        query_ref = query_ref.where("timestamp", ">=", start_datetime)
        query_ref = query_ref.where("timestamp", "<=", end_datetime)
        
        # Executar a consulta
        reports = []
        for doc in query_ref.get().docs:
            report_data = doc.to_dict()
            report_data["id"] = doc.id  # Adicionar o ID do documento
            reports.append(report_data)
            
        logger.info(f"Encontrados {len(reports)} relatórios no intervalo de {start_date} a {end_date}")
        
        if not reports:
            return {
                "success": True, 
                "message": "Nenhum relatório encontrado para o período especificado", 
                "reports": []
            }
            
        return {"success": True, "reports": reports}
        
    except Exception as e:
        import traceback
        logger.error(f"Erro ao buscar relatórios: {str(e)}")
        traceback.print_exc()
        return {"success": False, "error": str(e), "reports": []}