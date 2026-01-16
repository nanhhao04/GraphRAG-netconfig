GRAPH_EXTRACTION_PROMPT = """
-Goal-
Given a network configuration file (YAML format) that defines the topology of a Data Center, identify all entities and relationships.
The input is based on 'networkd/netplan' format containing definitions for Ethernets, Bonds, VLANs, and Routes.

-Strict Formatting Rules-
1. Do NOT wrap fields in parentheses inside the delimiters.
2. Do NOT add trailing characters like ')**' or '**' at the end of fields.
3. Clean raw values.

-Steps-
1. Identify all entities. For each identified entity, extract the following information:
- entity_name: **CRITICAL FOR UNIQUENESS**:
    - If entity is a **DEVICE**, use the hostname (e.g., 'SPINE_ROUTER_01').
    - If entity is an **INTERFACE/BOND/VLAN**, you MUST prefix it with the Device Name to ensure uniqueness. Format: <DEVICE_NAME>_<INTERFACE_NAME> (e.g., 'SPINE_ROUTER_01_ETH_TO_LEAF3').
    - If entity is an **IP_ADDRESS**, keep it as is (e.g., '10.0.1.1/30').
- entity_type: One of the following types: [{entity_types}]
- entity_description: The description MUST be a comprehensive summary of the entity ITSELF and ALL its nested configuration details found in the YAML. Convert the nested YAML structure into a readable English paragraph.
Format each entity as: "entity"{tuple_delimiter}<entity_name>{tuple_delimiter}<entity_type>{tuple_delimiter}<entity_description>

2. Identify relationships between the entities identified in step 1.
- source_entity: Exact <entity_name> from Step 1.
- target_entity: Exact <entity_name> from Step 1.
- relationship_description: explanation (e.g., HAS_INTERFACE, HAS_IP, ROUTES_TO, AGGREGATES).
- relationship_strength: Only a numeric integer (e.g., 10, 8, 6). Do NOT add text.
Format each relationship as: "relationship"{tuple_delimiter}<source_entity>{tuple_delimiter}<target_entity>{tuple_delimiter}<relationship_description>{tuple_delimiter}<relationship_strength>

3. Return output as a single list. Use **{record_delimiter}** as the list delimiter.
4. When finished, output {completion_delimiter}

######################
-Examples-
######################
Example 1: (Device containing Interface & IP)
Text:
# NODE 1: SPINE ROUTER 01
network:
  ethernets:
    eth_to_leaf3:
      mtu: 9000
      addresses: ["10.0.1.1/30"]
######################
Output:
"entity"{tuple_delimiter}SPINE ROUTER 01{tuple_delimiter}DEVICE{tuple_delimiter}High Performance L3 Core Router, Node 1. Configuration includes section 'ethernets' which defines interface 'eth_to_leaf3'.
{record_delimiter}
"entity"{tuple_delimiter}SPINE ROUTER 01_ETH_TO_LEAF3{tuple_delimiter}INTERFACE{tuple_delimiter}Physical interface on Spine 01. Configured with MTU 9000.
{record_delimiter}
"entity"{tuple_delimiter}10.0.1.1/30{tuple_delimiter}IP_ADDRESS{tuple_delimiter}IP Subnet assigned to interface.
{record_delimiter}
"relationship"{tuple_delimiter}SPINE ROUTER 01{tuple_delimiter}SPINE ROUTER 01_ETH_TO_LEAF3{tuple_delimiter}HAS_INTERFACE{tuple_delimiter}10
{record_delimiter}
"relationship"{tuple_delimiter}SPINE ROUTER 01_ETH_TO_LEAF3{tuple_delimiter}10.0.1.1/30{tuple_delimiter}HAS_IP{tuple_delimiter}10
{completion_delimiter}

Example 2: (Routing Logic)
Text:
# NODE 9: EDGE ROUTER 01
network:
  routes:
    - to: 172.16.0.0/16
      via: 10.200.1.2
######################
Output:
"entity"{tuple_delimiter}EDGE ROUTER 01{tuple_delimiter}DEVICE{tuple_delimiter}Primary WAN Gateway with routing configuration.
{record_delimiter}
"entity"{tuple_delimiter}172.16.0.0/16{tuple_delimiter}IP_ADDRESS{tuple_delimiter}Destination Network Subnet.
{record_delimiter}
"relationship"{tuple_delimiter}EDGE ROUTER 01{tuple_delimiter}172.16.0.0/16{tuple_delimiter}ROUTES_TO via 10.200.1.2{tuple_delimiter}6
{completion_delimiter}

######################
-Real Data-
######################
Entity_types: {entity_types}
Text: {input_text}
######################
Output:
"""