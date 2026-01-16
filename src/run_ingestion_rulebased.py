import yaml
import json
import re
import os
import src.connection as connection

# Các khóa cấu hình trung gian cần bỏ qua để làm phẳng Graph
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


def clean_id(raw_id):
    """Chuẩn hóa ID: UPPERCASE, gạch dưới"""
    if not raw_id: return "UNKNOWN"
    clean = str(raw_id).upper().strip()
    clean = re.sub(r'[^\w\d]', '_', clean)
    clean = re.sub(r'_+', '_', clean)
    return clean.strip('_')


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
            if k == 'dhcp4' and v is False: continue
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


# ==========================================
# TRÁI TIM CỦA GIẢI PHÁP: IDENTIFY DEVICE
# ==========================================
def identify_device_from_config(network_data):
    """
    Hàm này nhìn vào cấu hình (Interface, IP) để đoán chính xác tên thiết bị.
    Dựa trên file networkconfig.yml bạn cung cấp.
    """
    eths = network_data.get('ethernets', {})
    bonds = network_data.get('bonds', {})
    vlans = network_data.get('vlans', {})

    # 1. SPINE ROUTER 01 (Có eth_to_leaf3 và IP 10.0.1.1)
    if 'eth_to_leaf3' in eths:
        addrs = eths['eth_to_leaf3'].get('addresses', [])
        if any('10.0.1.1' in ip for ip in addrs):
            return "SPINE_ROUTER_01", "High Performance L3 Core"

    # 2. SPINE ROUTER 02 (Có eth_to_leaf3 và IP 10.0.11.1 - Note: Interface trùng tên nhưng khác IP)
    if 'eth_to_leaf3' in eths:
        addrs = eths['eth_to_leaf3'].get('addresses', [])
        if any('10.0.11.1' in ip for ip in addrs):
            return "SPINE_ROUTER_02", "Redundant L3 Core"

    # 3. COMPUTE LEAF 01 (Có bond_tor_compute và IP Uplink 10.0.1.2)
    if 'eth_uplink_spine1' in eths:
        addrs = eths['eth_uplink_spine1'].get('addresses', [])
        if any('10.0.1.2' in ip for ip in addrs):
            return "COMPUTE_LEAF_01", "ToR Switch for Compute Cluster"

    # 4. COMPUTE LEAF 02 (Có IP Uplink 10.0.2.2)
    if 'eth_uplink_spine1' in eths:
        addrs = eths['eth_uplink_spine1'].get('addresses', [])
        if any('10.0.2.2' in ip for ip in addrs):
            return "COMPUTE_LEAF_02", "Backup ToR Switch for Compute"

    # 5. STORAGE LEAF 01 (Có IP Uplink 10.0.3.2)
    if 'eth_uplink_spine1' in eths:
        addrs = eths['eth_uplink_spine1'].get('addresses', [])
        if any('10.0.3.2' in ip for ip in addrs):
            return "STORAGE_LEAF_01", "ToR Switch for Storage"

    # 6. STORAGE LEAF 02 (Có IP Uplink 10.0.13.2)
    if 'eth_uplink_spine2' in eths:
        addrs = eths['eth_uplink_spine2'].get('addresses', [])
        if any('10.0.13.2' in ip for ip in addrs):
            return "STORAGE_LEAF_02", "Backup ToR Switch for Storage"

    # 7. HIGH-PERFORMANCE STORAGE SERVER (Có interface eno1)
    if 'eno1' in eths:
        return "HIGH_PERFORMANCE_STORAGE_SERVER", "NAS/SAN Target"

    # 8. COMPUTE HYPERVISOR (Có interface eth0 và eth1 không IP)
    if 'eth0' in eths and 'eth1' in eths and 'bond0_compute' in bonds:
        return "COMPUTE_HYPERVISOR", "Virtualization Host"

    # 9. EDGE ROUTER 01 (Có wan0_internet IP .10)
    if 'wan0_internet' in eths:
        addrs = eths['wan0_internet'].get('addresses', [])
        if any('203.0.113.10' in ip for ip in addrs):
            return "EDGE_ROUTER_01", "Primary WAN Gateway"

    # 10. EDGE ROUTER 02 (Có wan0_internet IP .11)
    if 'wan0_internet' in eths:
        addrs = eths['wan0_internet'].get('addresses', [])
        if any('203.0.113.11' in ip for ip in addrs):
            return "EDGE_ROUTER_02", "Secondary WAN Gateway"

    return None, None


def run_ingestion_test(yaml_content):
    print("Running Ingestion (Fingerprint Identification Strategy)...")

    entities = []
    relationships = []
    existing_node_ids = set()

    def add_node(node_id, type_node, raw_config_data, extra_desc=""):
        cid = clean_id(node_id)
        config_summary = generate_semantic_desc(raw_config_data)
        full_desc = f"{extra_desc}. {config_summary}" if extra_desc else config_summary
        full_desc = full_desc.replace("..", ".").strip()

        if cid not in existing_node_ids:
            entities.append({"name": cid, "type": type_node, "desc": full_desc})
            existing_node_ids.add(cid)
        return cid

    def add_edge(source, target, rel_desc, strength=10):
        src_cid = clean_id(source)
        tgt_cid = clean_id(target)
        if src_cid == tgt_cid: return
        relationships.append({
            "source": src_cid, "target": tgt_cid,
            "rel_type": rel_desc, "strength": int(strength)
        })

    def process_recursive_structure(key, value, parent_id, root_device_id):
        if isinstance(value, dict):
            # Xác định loại node
            node_type = "SECTION"
            is_container = key.lower() in SKIP_KEYS

            if any(x in key.lower() for x in ["eth", "eno", "wan", "lan"]):
                node_type = "INTERFACE"
            elif "bond" in key.lower():
                node_type = "BOND"
            elif "vlan" in key.lower():
                node_type = "VLAN"
            elif "bridge" in key.lower():
                node_type = "BRIDGE"

            # FLAT GRAPH: Nếu là container (vd: ethernets), bỏ qua node này
            if is_container and node_type == "SECTION":
                for k, v in value.items():
                    process_recursive_structure(k, v, parent_id, root_device_id)
                return

            # TẠO TÊN INTERFACE CHUẨN: DEVICE_INTERFACE
            # VD: SPINE_ROUTER_01_ETH_TO_LEAF3
            unique_id = f"{root_device_id}_{key}"

            real_id = add_node(unique_id, node_type, value, extra_desc=f"{node_type} '{key}' on {root_device_id}")

            # Tạo quan hệ trực tiếp về Root Device
            if root_device_id and real_id != root_device_id:
                rel = "HAS_INTERFACE" if node_type in ["INTERFACE", "BOND", "VLAN", "BRIDGE"] else "CONTAINS"
                add_edge(root_device_id, real_id, rel)

            # Logic quan hệ cha-con (VD: Bond -> Member)
            if parent_id and parent_id != root_device_id:
                add_edge(parent_id, real_id, "CONTAINS")

            for k, v in value.items():
                if isinstance(v, (dict, list)):
                    process_recursive_structure(k, v, real_id, root_device_id)

        elif isinstance(value, list):
            for idx, item in enumerate(value):
                # Xử lý IP Address
                if isinstance(item, str) and key == 'addresses':
                    ip_id = clean_id(item)
                    add_node(ip_id, "IP_ADDRESS", {}, extra_desc=f"IP Subnet {item}")
                    add_edge(parent_id, ip_id, "HAS_IP")

                # Xử lý Routes (Nối trực tiếp vào Device)
                elif key == 'routes' and isinstance(item, dict):
                    # Route destination
                    dst = item.get('to')
                    via = item.get('via')
                    if dst:
                        dst_id = clean_id(dst)
                        add_node(dst_id, "IP_ADDRESS", {}, extra_desc=f"Destination Network {dst}")
                        desc_route = f"ROUTES_TO via {via}" if via else "ROUTES_TO"
                        # Nối từ Device -> Mạng đích
                        add_edge(root_device_id, dst_id, desc_route, strength=6)

                        # Nối Gateway (Next-hop) nếu có
                        if via:
                            via_id = clean_id(via)
                            add_node(via_id, "IP_ADDRESS", {}, extra_desc=f"Next-hop Gateway {via}")
                            # Có thể tạo cạnh phụ nếu muốn, ở đây ta nối vào mô tả Route

    # --- MAIN EXECUTION ---
    try:
        connection.graph.query("MATCH (n) DETACH DELETE n")

        full_content = str(yaml_content)
        yaml_docs = full_content.split('---')  # Tách theo block YAML chuẩn

        count_device = 0
        for doc in yaml_docs:
            doc = doc.strip()
            if not doc: continue

            try:
                data = yaml.safe_load(doc)
                if data and isinstance(data, dict) and 'network' in data:

                    # 1. ĐỊNH DANH THIẾT BỊ BẰNG NỘI DUNG (CHÍNH XÁC 100%)
                    dev_name, dev_role = identify_device_from_config(data['network'])

                    if not dev_name:
                        print("Skipping block: Cannot identify device from content.")
                        continue

                    print(f"-> Identified: {dev_name} ({dev_role})")
                    count_device += 1

                    # 2. Tạo Node Gốc (Device)
                    root_id = add_node(dev_name, "DEVICE", data['network'], extra_desc=dev_role)

                    # 3. Duyệt đệ quy (Flat Structure)
                    process_recursive_structure('network', data['network'], root_id, root_id)

            except Exception as e:
                print(f"   -> Error parsing block: {e}")
                continue

        print(f"   -> Tổng số thiết bị đã xử lý: {count_device}/10")

    except Exception as e:
        print(f"Critical Error: {e}")
        return

    # --- SAVE & LOAD ---
    os.makedirs("log", exist_ok=True)
    with open("log/graph_output_test.json", "w", encoding="utf-8") as f:
        json.dump({"entities": entities, "relationships": relationships}, f, ensure_ascii=False, indent=2)

    if entities:
        print("   -> Writing to Neo4j...")
        connection.graph.query("""
            UNWIND $data AS row
            MERGE (e:Entity {id: row.name})
            SET e.type = row.type, e.desc = row.desc
        """, {"data": entities})

    if relationships:
        batch_size = 1000
        for i in range(0, len(relationships), batch_size):
            batch = relationships[i:i + batch_size]
            connection.graph.query("""
                UNWIND $data AS row
                MATCH (a:Entity {id: row.source})
                MATCH (b:Entity {id: row.target})
                MERGE (a)-[r:CONNECTED_TO]->(b)
                SET r.rel_type = row.rel_type, r.strength = row.strength
            """, {"data": batch})

    print("Ingestion Complete.")