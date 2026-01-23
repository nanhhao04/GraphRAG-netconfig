import yaml
import json
import re
import os
import unicodedata
import src.connection as connection


OUTPUT_JSON = "log/graph_output_test.json"
SKIP_KEYS = {'network', 'ethernets', 'bonds', 'vlans', 'bridges', 'version', 'renderer'}
KEY_MAP = {
    "mtu": "MTU size", "addresses": "assigned IPs",
    "gateway4": "gateway", "dhcp4": "DHCP status",
    "id": "VLAN ID", "link": "uplink bond",
    "mode": "mode", "lacp-rate": "LACP rate",
    "to": "destination", "via": "next-hop",
    "metric": "metric", "interfaces": "member interfaces",
    "parameters": "parameters", "transmit-hash-policy": "hash policy",
    "mii-monitor-interval": "monitor interval"
}

# Globals
entities = []
relationships = []
node_ids = set()

def remove_accents(input_str):
    if not input_str: return ""
    nfkd_form = unicodedata.normalize('NFKD', str(input_str))
    return "".join([c for c in nfkd_form if not unicodedata.combining(c)])


def clean_id(raw):
    if not raw: return "UNKNOWN"

    raw = remove_accents(str(raw)) # bỏ dấu tiếng việt
    raw = raw.upper().strip()
    raw = re.sub(r'[^\w\d]', '_', raw)
    raw = re.sub(r'_+', '_', raw)
    return raw.strip('_')


def extract_device_names_from_raw(raw_text):
    blocks = re.split(r'\n---\s*\n', raw_text)
    names = []

    for idx, block in enumerate(blocks):
        name = None
        for line in block.strip().splitlines():
            line = line.strip()
            if line.startswith("#"):
                found_raw_name = None

                m = re.search(r'DEVICE\s*:\s*(.+)', line, re.IGNORECASE)
                if m:
                    found_raw_name = m.group(1).strip()

                else:
                    content = line.lstrip("#").strip()
                    if content and "CONFIG" not in content.upper():
                        found_raw_name = content

                if found_raw_name:
                    name = re.sub(r'\s*\(.*?\)', '', found_raw_name).strip()
                    break

            if line and not line.startswith("#"):
                break  # Dừng nếu gặp content không phải comment

        names.append(name if name else f"DEVICE_{idx + 1}")

    return names

def format_list_items(key, value_list):
    if not value_list: return ""
    try:
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
            return f"Routes: {'; '.join(items_desc)}"
    except:
        pass
    return f"{key}: {str(value_list)}"


def generate_semantic_desc(data):
    if isinstance(data, dict):
        sentences = []
        primitives = {k: v for k, v in data.items() if not isinstance(v, (dict, list))}
        complex_data = {k: v for k, v in data.items() if isinstance(v, (dict, list))}

        props_str = []
        for k, v in primitives.items():
            if k in ['renderer', 'version', 'optional']: continue
            human_key = KEY_MAP.get(k, k)
            props_str.append(f"{human_key} {v}")
        if props_str: sentences.append(", ".join(props_str) + ".")

        for k, v in complex_data.items():
            if isinstance(v, list):
                list_desc = format_list_items(k, v)
                if list_desc: sentences.append(list_desc)
            elif isinstance(v, dict):
                child_desc = generate_semantic_desc(v)
                if child_desc: sentences.append(f"Section '{k}': [{child_desc}]")

        return " ".join([s for s in sentences if s])
    elif isinstance(data, list):
        return format_list_items("items", data)
    return str(data)


def add_entity(raw_id, etype, info=None):
    cid = clean_id(raw_id)
    # Tạo mô tả (Desc) từ info
    semantic_desc = generate_semantic_desc(info) if info else f"{etype} {cid}"

    # Tạo JSON info
    try:
        infor_str = json.dumps(info, ensure_ascii=False)
    except:
        infor_str = str(info)

    if cid not in node_ids:
        entities.append({
            "name": cid,
            "type": etype,
            "desc": semantic_desc,
            "infor": infor_str
        })
        node_ids.add(cid)
    return cid

def add_relation(src, tgt, rel_type):
    s = clean_id(src)
    t = clean_id(tgt)
    if s != t:
        relationships.append({
            "source": s,
            "target": t,
            "rel_type": rel_type,
            "strength": 10
        })

def walk(key, value, parent_id, root_device_id):
    # DICT (Sections)
    if isinstance(value, dict):
        node_type = "SECTION"
        k_lower = key.lower()

        # Xác định Type
        if any(x in k_lower for x in ["eth", "eno", "wan", "lan"]):
            node_type = "INTERFACE"
        elif "bond" in k_lower:
            node_type = "BOND"
        elif "vlan" in k_lower:
            node_type = "VLAN"
        elif "bridge" in k_lower:
            node_type = "BRIDGE"

        # Nếu là key cấu trúc (ethernets...), chỉ duyệt con
        if k_lower in SKIP_KEYS:
            for ck, cv in value.items():
                walk(ck, cv, parent_id, root_device_id)
            return

        # Tạo Node
        # ID = Root + Key (VD: DEVICE_1_ETH0)
        current_node_id = f"{root_device_id}_{key}"

        # {key: value} vào info
        nid = add_entity(current_node_id, node_type, info={key: value})
        add_relation(parent_id, nid, "CONTAINS")

        # Đệ quy xuống con
        for ck, cv in value.items():
            walk(ck, cv, nid, root_device_id)

    # LIST (IPs, Routes)
    elif isinstance(value, list):
        for item in value:
            # IP Address
            if key == "addresses" and isinstance(item, str):
                ip_id = add_entity(item, "IP_ADDRESS", info={"address": item})
                add_relation(parent_id, ip_id, "HAS_IP")

            # Routes
            elif key == "routes" and isinstance(item, dict):
                dst = item.get("to")
                via = item.get("via")

                if dst:
                    dst_id = add_entity(dst, "IP_NETWORK", info=item)
                    add_relation(root_device_id, dst_id, "ROUTES_TO")  # Nối từ Root Device

                if via:
                    via_id = add_entity(via, "IP_ADDRESS", info={"gateway": via})
                    add_relation(root_device_id, via_id, "NEXT_HOP")  # Nối từ Root Device


def run_ingestion_test(yaml_content):
    print("[Ingestion Refined] Starting (Based on Reference Code)...")

    # Reset globals
    entities.clear()
    relationships.clear()
    node_ids.clear()

    try:
        raw_text = str(yaml_content)

        # 1. Lấy tên từ comment (Logic tham chiếu)
        device_names = extract_device_names_from_raw(raw_text)
        print(f"   -> Detected Names: {device_names}")

        # 2. Parse YAML
        docs = list(yaml.safe_load_all(raw_text))

        device_idx = 0
        for doc in docs:
            if not doc or "network" not in doc:
                continue

            # Lấy tên tương ứng
            dev_name_raw = device_names[device_idx] if device_idx < len(device_names) else f"DEVICE_{device_idx + 1}"
            device_idx += 1

            # Tạo Root Node (Device)
            root_id = add_entity(dev_name_raw, "DEVICE", info=doc["network"])
            print(f"   -> Processing: {dev_name_raw} ==> ID: {root_id}")

            # Bắt đầu duyệt đệ quy (Walk)
            for k, v in doc["network"].items():
                walk(k, v, root_id, root_id)

        # 3. Save JSON Log
        os.makedirs("log", exist_ok=True)
        with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
            json.dump({
                "entities": entities,
                "relationships": relationships
            }, f, indent=2, ensure_ascii=False)

        print(f"   -> Extracted {len(entities)} Entities & {len(relationships)} Relationships.")
        print(f"   -> Log saved: {OUTPUT_JSON}")

        # 4. Write to Neo4j (Phần này phải giữ lại để hệ thống chạy được)
        print("   -> Writing to Neo4j...")
        connection.graph.query("MATCH (n) DETACH DELETE n")

        if entities:
            connection.graph.query("""
                UNWIND $data AS row
                MERGE (e:Entity {id: row.name})
                SET e.type = row.type, 
                    e.desc = row.desc,
                    e.infor = row.infor
            """, {"data": entities})

        if relationships:
            # Batch write edges
            batch_size = 1000
            for i in range(0, len(relationships), batch_size):
                batch = relationships[i:i + batch_size]
                connection.graph.query("""
                    UNWIND $data AS row
                    MATCH (a:Entity {id: row.source})
                    MATCH (b:Entity {id: row.target})
                    MERGE (a)-[r:CONNECTED_TO]->(b)
                    SET r.rel_type = row.rel_type,
                        r.strength = row.strength,
                        r.desc = row.rel_type
                """, {"data": batch})

        print("   -> Ingestion Complete!")

    except Exception as e:
        print(f"Critical Error: {e}")
        import traceback
        traceback.print_exc()

