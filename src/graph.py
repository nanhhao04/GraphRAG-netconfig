from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from langchain_community.vectorstores import Neo4jVector

# Import Connection
from src.connection import graph, llm, embeddings
# Import Prompts
from src.prompt.index.extract_graph import GRAPH_EXTRACTION_PROMPT
from src.prompt.index.community_report import COMMUNITY_REPORT_PROMPT


# --- 1. INGESTION PHASE ---
def run_ingestion(yaml_content):
    print("[1/3] Running Extraction...")

    prompt = PromptTemplate.from_template(GRAPH_EXTRACTION_PROMPT)
    chain = prompt | llm | JsonOutputParser()

    # Gọi LLM
    try:
        data = chain.invoke({
            "input_text": str(yaml_content),
            "format_instructions": "Return JSON with keys: 'devices' (list) and 'connections' (list)."
        })
    except Exception as e:
        print(f"Extraction Failed: {e}")
        return

    # Nạp vào Neo4j
    print("   -> Writing to Neo4j...")
    graph.query("MATCH (n) DETACH DELETE n")  # Reset DB

    for dev in data.get('devices', []):
        graph.query(
            "MERGE (d:Device {id: $name}) SET d.type=$type, d.desc=$desc",
            {"name": dev['name'], "type": dev.get('type', 'Device'), "desc": dev.get('description', '')}
        )

    for conn in data.get('connections', []):
        graph.query(
            """
            MATCH (a:Device {id: $src}), (b:Device {id: $tgt})
            MERGE (a)-[r:CONNECTED_TO]->(b)
            SET r.type = $type
            """,
            {"src": conn['source'], "tgt": conn['target'], "type": conn.get('relation_type', 'LINK')}
        )

    run_leiden()


# CLUSTERING PHASE (LEIDEN)
def run_leiden():
    print("[2/3] Running Leiden Algorithm...")
    try:
        # Drop cũ
        graph.query("CALL gds.graph.drop('net_graph', false)")

        # Project Graph
        graph.query("""
            CALL gds.graph.project(
                'net_graph',
                'Device',
                {CONNECTED_TO: {orientation: 'UNDIRECTED'}}
            )
        """)

        # Run Leiden & Write communityId
        res = graph.query("""
            CALL gds.leiden.write(
                'net_graph',
                {writeProperty: 'communityId'}
            ) YIELD communityCount
        """)
        print(f"   -> Found {res[0]['communityCount']} communities.")

        # Cleanup
        graph.query("CALL gds.graph.drop('net_graph', false)")

        run_summarization()

    except Exception as e:
        print(f"Leiden Error (Check GDS Plugin): {e}")


# --- 3. SUMMARIZATION PHASE ---
def run_summarization():
    print("[3/3] Generating Community Reports...")

    # Lấy danh sách Community ID
    cids = graph.query("MATCH (d:Device) RETURN distinct d.communityId as cid")

    prompt = PromptTemplate.from_template(COMMUNITY_REPORT_PROMPT)
    chain = prompt | llm | JsonOutputParser()

    for record in cids:
        cid = record['cid']
        if cid is None: continue

        # Lấy context của cụm
        members = graph.query(
            "MATCH (d:Device {communityId: $cid}) RETURN d.id, d.desc",
            {"cid": cid}
        )
        context_text = "\n".join([f"- {m['d.id']}: {m['d.desc']}" for m in members])

        # Gọi LLM tóm tắt
        try:
            report = chain.invoke({"input_text": context_text})

            # Lưu Node Community
            graph.query("""
                MERGE (c:Community {id: $cid})
                SET c.title = $title, c.summary = $summary, c.rating = $rating
                WITH c
                MATCH (d:Device {communityId: $cid})
                MERGE (d)-[:IN_COMMUNITY]->(c)
            """, {
                "cid": cid,
                "title": report.get('title', f"Cluster {cid}"),
                "summary": report.get('summary', ''),
                "rating": report.get('rating', 0)
            })
        except Exception as e:
            print(f"   -> Error summarizing cluster {cid}: {e}")

    # Cuối cùng: Tạo Vector Index
    create_indices()


def create_indices():
    print("Creating Vector Indices...")
    # 1. Entity Index (cho Local Search)
    try:
        Neo4jVector.from_existing_graph(
            embedding=embeddings,
            url=graph._url, username=graph._username, password=graph._password,
            index_name="entity_index",
            node_label="Device",
            text_node_properties=["id", "desc"],
            embedding_node_property="embedding"
        )
        print("   -> Entity Index Created.")
    except:
        pass

    print("Build Complete!")