

import os
import yaml
from langchain_community.graphs import Neo4jGraph
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from neo4j import GraphDatabase


# Load Config
def load_config():
    # Giả sử chạy từ root
    config_path = "config.yml"
    if not os.path.exists(config_path):
        # Fallback nếu chạy từ src
        config_path = "../config.yml"

    try:
        with open(config_path, "r") as f:
            return yaml.load(f, Loader=yaml.FullLoader)
    except:
        return {}


cfg = load_config()

# Global Instances
graph = None
llm = None
embeddings = None


def init_connections():
    global graph, llm, embeddings

    # 1. Setup Gemini
    api_key = cfg.get("GOOGLE_API_KEY")
    if api_key:
        llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", google_api_key=api_key, temperature=0)
        embeddings = GoogleGenerativeAIEmbeddings(model="models/text-embedding-004", google_api_key=api_key)
        print(" Gemini Connected")

    # 2. Setup Neo4j
    uri = cfg.get("NEO4J_URI")
    user = cfg.get("NEO4J_USERNAME")
    pwd = cfg.get("NEO4J_PASSWORD")

    if uri and user and pwd:
        try:
            graph = Neo4jGraph(url=uri, username=user, password=pwd)
            # Test query nhẹ
            graph.query("RETURN 1")
            print(" Neo4j Connected")
        except Exception as e:
            print(f" Neo4j Error: {e}")