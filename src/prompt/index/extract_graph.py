GRAPH_EXTRACTION_PROMPT = """
-Goal-
Given a network configuration file (YAML format) that defines the topology of a Data Center, identify all entities and relationships.
The input is based on 'networkd/netplan' format containing definitions for Ethernets, Bonds, VLANs, and Routes.

-Steps-
1. Identify all entities. For each identified entity, extract the following information:
- entity_name: Name of the entity, capitalized. Use the 'NODE X: NAME' from comments or interface names if explicit.
- entity_type: One of the following types: [{entity_types}]
- entity_description: **CRITICAL**: The description MUST be a comprehensive summary of the entity ITSELF and ALL its nested configuration details found in the YAML.
    - If the entity is a **DEVICE**, the description must summarize ALL its interfaces, bonds, VLANs, IPs, and Routes.
    - If the entity is an **INTERFACE/BOND**, the description must summarize its MTU, assigned IPs, member ports, and link parameters.
    - Do not leave out child attributes. Convert the nested YAML structure into a readable English paragraph.
Format each entity as ("entity"{tuple_delimiter}<entity_name>{tuple_delimiter}<entity_type>{tuple_delimiter}<entity_description>)

2. From the entities identified in step 1, identify all pairs of (source_entity, target_entity) that are *clearly related* to each other.
For each pair of related entities, extract the following information:
- source_entity: name of the source entity
- target_entity: name of the target entity
- relationship_description: explanation (e.g., Physical uplink, LACP Member, VLAN Tagging, Static Route via Next-hop).
- relationship_strength: numeric score (10 for Physical/Direct, 8 for Aggregation/Bonding, 6 for Routing/Logical).
 Format each relationship as ("relationship"{tuple_delimiter}<source_entity>{tuple_delimiter}<target_entity>{tuple_delimiter}<relationship_description>{tuple_delimiter}<relationship_strength>)

3. Return output in English as a single list of all the entities and relationships identified in steps 1 and 2. Use **{record_delimiter}** as the list delimiter.

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
("entity"{tuple_delimiter}SPINE ROUTER 01{tuple_delimiter}DEVICE{tuple_delimiter}High Performance L3 Core Router, Node 1. Configuration includes section 'ethernets' which defines interface 'eth_to_leaf3' with MTU 9000 and assigned IP 10.0.1.1/30.)
{record_delimiter}
("entity"{tuple_delimiter}ETH_TO_LEAF3{tuple_delimiter}INTERFACE{tuple_delimiter}Physical interface on Spine 01. Configured with MTU 9000 and holds IP address 10.0.1.1/30.)
{record_delimiter}
("entity"{tuple_delimiter}10.0.1.1/30{tuple_delimiter}IP_ADDRESS{tuple_delimiter}IP Subnet 10.0.1.1/30 assigned to interface eth_to_leaf3.)
{record_delimiter}
("relationship"{tuple_delimiter}SPINE ROUTER 01{tuple_delimiter}ETH_TO_LEAF3{tuple_delimiter}HAS_INTERFACE{tuple_delimiter}10)
{record_delimiter}
("relationship"{tuple_delimiter}ETH_TO_LEAF3{tuple_delimiter}10.0.1.1/30{tuple_delimiter}HAS_IP{tuple_delimiter}10)
{completion_delimiter}

Example 2: (Device containing Bond, Members & VLANs)
Text:
# NODE 3: COMPUTE LEAF 01
network:
  bonds:
    bond_tor_compute:
      interfaces: [eth_downlink_srv8]
      parameters: {{mode: 802.3ad}}
  vlans:
    vlan10_mgmt:
      id: 10
      link: bond_tor_compute
      addresses: ["192.168.1.253/24"]
######################
Output:
("entity"{tuple_delimiter}COMPUTE LEAF 01{tuple_delimiter}DEVICE{tuple_delimiter}Top-of-Rack Switch for Compute Cluster. Contains Bond 'bond_tor_compute' (Mode 802.3ad, member 'eth_downlink_srv8'). Also contains VLAN 'vlan10_mgmt' (ID 10) linked to the bond with IP 192.168.1.253/24.)
{record_delimiter}
("entity"{tuple_delimiter}BOND_TOR_COMPUTE{tuple_delimiter}INTERFACE{tuple_delimiter}LACP Bond Interface. Parameters: mode 802.3ad. Aggregates physical interface 'eth_downlink_srv8'.)
{record_delimiter}
("entity"{tuple_delimiter}ETH_DOWNLINK_SRV8{tuple_delimiter}INTERFACE{tuple_delimiter}Physical member port part of bond_tor_compute.)
{record_delimiter}
("entity"{tuple_delimiter}VLAN10_MGMT{tuple_delimiter}INTERFACE{tuple_delimiter}VLAN Interface with ID 10. Linked to parent 'bond_tor_compute'. Assigned IP 192.168.1.253/24.)
{record_delimiter}
("relationship"{tuple_delimiter}COMPUTE LEAF 01{tuple_delimiter}BOND_TOR_COMPUTE{tuple_delimiter}HAS_INTERFACE{tuple_delimiter}10)
{record_delimiter}
("relationship"{tuple_delimiter}BOND_TOR_COMPUTE{tuple_delimiter}ETH_DOWNLINK_SRV8{tuple_delimiter}AGGREGATES member port{tuple_delimiter}9)
{record_delimiter}
("relationship"{tuple_delimiter}VLAN10_MGMT{tuple_delimiter}BOND_TOR_COMPUTE{tuple_delimiter}TAGGED_ON parent link{tuple_delimiter}8)
{completion_delimiter}

Example 3: (Routing Logic)
Text:
# NODE 9: EDGE ROUTER 01
network:
  routes:
    - to: 172.16.0.0/16
      via: 10.200.1.2
######################
Output:
("entity"{tuple_delimiter}EDGE ROUTER 01{tuple_delimiter}DEVICE{tuple_delimiter}Primary WAN Gateway. Routing Table includes: Route to network 172.16.0.0/16 via next-hop gateway 10.200.1.2.)
{record_delimiter}
("entity"{tuple_delimiter}172.16.0.0/16{tuple_delimiter}IP_ADDRESS{tuple_delimiter}Destination Network Subnet.)
{record_delimiter}
("relationship"{tuple_delimiter}EDGE ROUTER 01{tuple_delimiter}172.16.0.0/16{tuple_delimiter}ROUTES_TO via 10.200.1.2{tuple_delimiter}6)
{completion_delimiter}

######################
-Real Data-
######################
Entity_types: {entity_types}
Text: {input_text}
######################
Output:"""