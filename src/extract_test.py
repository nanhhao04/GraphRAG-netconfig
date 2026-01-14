import yaml
import re
import src.connection as connection  # Đảm bảo import connection

# ==========================================
# 1. CẤU HÌNH TỪ ĐIỂN DỊCH THUẬT (SEMANTIC MAP)
# ==========================================
KEY_MAP = {
    "mtu": "MTU size set to",
    "addresses": "assigned IP addresses",
    "gateway4": "uses default gateway",
    "dhcp4": "DHCPv4 status",
    "id": "VLAN ID",
    "link": "uplinked via bond",
    "mode": "operating mode",
    "lacp-rate": "LACP rate",
    "to": "destination network",
    "via": "next-hop gateway",
    "metric": "routing metric"
}


def format_list_items(key, value_list):
    """Xử lý danh sách thông minh để tạo văn bản"""
    if not value_list: return ""

    # Nếu list chứa string (VD: IP)
    if isinstance(value_list[0], str):
        return f"{KEY_MAP.get(key, key)} [{', '.join(value_list)}]"

    # Nếu list chứa dict (VD: Routes)
    if isinstance(value_list[0], dict):
        items_desc = []
        for item in value_list:
            if 'to' in item and 'via' in item:
                route_str = f"route to {item['to']} via {item['via']}"
                if 'metric' in item: route_str += f" (metric {item['metric']})"
                items_desc.append(route_str)
            else:
                items_desc.append(generate_semantic_desc(item))
        return f"Contains {len(value_list)} routes: {'; '.join(items_desc)}"

    return f"{key}: {str(value_list)}"


def generate_semantic_desc(data):
    """Biến Dict thành đoạn văn mô tả ngữ nghĩa (Semantic Paragraph)"""
    if isinstance(data, dict):
        sentences = []
        # Xử lý primitive
        primitives = {k: v for k, v in data.items() if not isinstance(v, (dict, list))}
        complex_data = {k: v for k, v in data.items() if isinstance(v, (dict, list))}

        props_str = []
        for k, v in primitives.items():
            if k in ['renderer', 'version', 'dhcp4', 'optional']: continue
            human_key = KEY_MAP.get(k, k)
            props_str.append(f"{human_key} {v}")

        if props_str:
            sentences.append(", ".join(props_str) + ".")

        # Xử lý complex (List/Dict)
        for k, v in complex_data.items():
            if isinstance(v, list):
                sentences.append(format_list_items(k, v))
            elif isinstance(v, dict):
                child_desc = generate_semantic_desc(v)
                if child_desc:
                    sentences.append(f"Section '{k}' configures: [{child_desc}]")

        return " ".join([s for s in sentences if s])

    elif isinstance(data, list):
        return format_list_items("items", data)

    return str(data)


# ==========================================
# 2. HÀM INGESTION CHÍNH
# ==========================================
def run_ingestion_test(yaml_content):
    print("[1/3] Running Extraction (Rule-based Semantic Parsing) - DEBUG MODE...")

    # --- 1. HELPER FUNCTIONS ---
    KEY_MAP = {
        "mtu": "MTU size set to", "addresses": "assigned IP addresses",
        "gateway4": "uses default gateway", "dhcp4": "DHCPv4 status",
        "id": "VLAN ID", "link": "uplinked via bond",
        "mode": "operating mode", "lacp-rate": "LACP rate",
        "to": "destination network", "via": "next-hop gateway",
        "metric": "routing metric"
    }

    def format_list_items(key, value_list):
        if not value_list: return ""
        if isinstance(value_list[0], str):
            return f"{KEY_MAP.get(key, key)} [{', '.join(value_list)}]"
        if isinstance(value_list[0], dict):
            items_desc = []
            for item in value_list:
                if 'to' in item and 'via' in item:
                    route_str = f"route to {item['to']} via {item['via']}"
                    if 'metric' in item: route_str += f" (metric {item['metric']})"
                    items_desc.append(route_str)
                else:
                    items_desc.append(generate_semantic_desc(item))
            return f"Contains {len(value_list)} routes: {'; '.join(items_desc)}"
        return f"{key}: {str(value_list)}"

    def generate_semantic_desc(data):
        if isinstance(data, dict):
            sentences = []
            primitives = {k: v for k, v in data.items() if not isinstance(v, (dict, list))}
            complex_data = {k: v for k, v in data.items() if isinstance(v, (dict, list))}

            props_str = []
            for k, v in primitives.items():
                if k in ['renderer', 'version', 'dhcp4', 'optional']: continue
                human_key = KEY_MAP.get(k, k)
                props_str.append(f"{human_key} {v}")
            if props_str: sentences.append(", ".join(props_str) + ".")

            for k, v in complex_data.items():
                if isinstance(v, list):
                    sentences.append(format_list_items(k, v))
                elif isinstance(v, dict):
                    child_desc = generate_semantic_desc(v)
                    if child_desc: sentences.append(f"Section '{k}' configures: [{child_desc}]")
            return " ".join([s for s in sentences if s])
        elif isinstance(data, list):
            return format_list_items("items", data)
        return str(data)

    # --- 2. GRAPH BUILDER ---
    nodes_list = []
    edges_list = []
    existing_node_names = set()

    def add_node(name, type_node, raw_config_data, extra_desc=""):
        name_upper = str(name).upper().replace(" ", "_")
        config_summary = generate_semantic_desc(raw_config_data)
        config_summary = config_summary.replace("Config Details:", "").strip()
        full_desc = f"{extra_desc}. {config_summary}" if extra_desc else config_summary

        if name_upper not in existing_node_names:
            nodes_list.append({"id": name_upper, "type": type_node, "desc": full_desc})
            existing_node_names.add(name_upper)
        return name_upper

    def add_edge(source, target, rel_type):
        edges_list.append({
            "source": str(source).upper().replace(" ", "_"),
            "target": str(target).upper().replace(" ", "_"),
            "type": rel_type
        })

    def process_recursive_structure(key, value, parent_name):
        current_name = key
        if isinstance(value, dict):
            node_type = "SECTION"
            if any(x in key for x in ["eth", "eno", "wan", "lan"]):
                node_type = "INTERFACE"
            elif "bond" in key:
                node_type = "BOND"
            elif "vlan" in key:
                node_type = "VLAN"
            elif key == "network":
                node_type = "CONFIG_ROOT"

            real_name = add_node(current_name, node_type, value, extra_desc=f"Configuration block for {key}")
            if parent_name:
                rel_type = "CONTAINS"
                if node_type in ["INTERFACE", "BOND", "VLAN"]: rel_type = "HAS_" + node_type
                add_edge(parent_name, real_name, rel_type)

            for k, v in value.items():
                if isinstance(v, (dict, list)):
                    process_recursive_structure(k, v, real_name)
        elif isinstance(value, list):
            for idx, item in enumerate(value):
                if isinstance(item, str) and key == 'addresses':
                    add_node(item, "IP_ADDRESS", {}, extra_desc=f"IP Address {item}")
                    add_edge(parent_name, item, "HAS_IP")
                elif isinstance(item, dict) and 'to' in item:
                    r_name = f"ROUTE_TO_{item['to']}"
                    r_desc = f"Static route to {item['to']} via {item.get('via', 'unknown')}"
                    add_node(r_name, "ROUTE", item, extra_desc="Routing entry")
                    add_edge(parent_name, r_name, "HAS_ROUTE")

    # --- 3. MAIN EXECUTION WITH LOGGING ---
    try:
        if not yaml_content:
            print("❌ ERROR: YAML content is EMPTY!")
            return

        raw_docs = [doc for doc in yaml_content.strip().split('---') if doc.strip()]
        print(f"   -> Found {len(raw_docs)} blocks. Checking content...")

        # Clear old data
        connection.graph.query("MATCH (n) DETACH DELETE n")

        for i, raw_doc in enumerate(raw_docs):
            print(f"\n   --- Processing Block {i + 1} ---")

            # Debug: In ra 50 ký tự đầu để xem format
            print(f"      [RAW PREVIEW]: {raw_doc.strip()[:50]}...")

            # 1. Thử Regex bắt tên
            match = re.search(r"#\s*NODE\s*\d+\s*:\s*([^(\n]+)(?:\(([^)]+)\))?", raw_doc)

            if match:
                device_name = match.group(1).strip()
                device_note = match.group(2).strip() if match.group(2) else "Network Device"
                print(f"      ✅ Regex Match: Name='{device_name}'")
            else:
                print("      ⚠️ Regex FAILED. Attempting fallback...")
                if "network:" in raw_doc:
                    device_name = f"UNKNOWN_DEVICE_{i}"
                    device_note = "Parsed from raw config"
                    print(f"      -> Fallback used: Name='{device_name}'")
                else:
                    print("      ❌ Skip: Not a valid network config block.")
                    continue

            # 2. Thử Parse YAML
            try:
                data = yaml.safe_load(raw_doc)
                if data is None:
                    print("      ❌ YAML Load returned None.")
                    continue

                print(f"      -> YAML Keys found: {list(data.keys())}")

                if 'network' in data:
                    root_name = add_node(device_name, "DEVICE", data['network'], extra_desc=device_note)
                    process_recursive_structure('network', data['network'], root_name)
                    print(f"      -> Processed successfully. Current Nodes: {len(nodes_list)}")
                else:
                    print("      ⚠️ Missing 'network' key in YAML data.")

            except Exception as e:
                print(f"      ❌ YAML Parse Error: {e}")

        print(f"\n   -> Saving {len(nodes_list)} nodes and {len(edges_list)} edges to Neo4j...")

        if nodes_list:
            connection.graph.query("""
                    UNWIND $nodes AS n
                    MERGE (e:Entity {id: n.id})
                    SET e.type = n.type, e.desc = n.desc
                """, {"nodes": nodes_list})

            # Chia nhỏ edge batch để tránh lỗi bộ nhớ nếu quá nhiều
            batch_size = 100
            for k in range(0, len(edges_list), batch_size):
                batch = edges_list[k:k + batch_size]
                # Query đơn giản hóa để đảm bảo chạy được
                for edge in batch:
                    connection.graph.query(f"""
                            MATCH (s:Entity {{id: $source}})
                            MATCH (t:Entity {{id: $target}})
                            MERGE (s)-[:{edge['type']}]->(t)
                        """, {"source": edge['source'], "target": edge['target']})
                print(f"      -> Saved edges batch {k}-{k + len(batch)}")

        print("   -> Extraction Complete!")

    except Exception as e:
        print(f"❌ CRITICAL ERROR: {e}")