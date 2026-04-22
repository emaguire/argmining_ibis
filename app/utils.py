from pydantic import BaseModel
from typing import List

################
# Node merging #
################

class node_merge(BaseModel):
    ids: List[str]
    text: str

class node_merge_output(BaseModel):
    merges: List[node_merge]

def new_ibis_aif():
    return {
        "AIF": {
            "nodes": [],
            "edges": []
        },
        "IBIS": {
            "issues": [],
            "positions": [],
            "arguments": []
        }
    }

def get_ibis_type(node_id, ibis_xaif):
    if node_id in ibis_xaif['IBIS']['issues']:
        return 'issue'
    elif node_id in ibis_xaif['IBIS']['positions']:
        return 'position'
    elif node_id in ibis_xaif['IBIS']['arguments']:
        return 'argument'

######################
# Structure checking #
######################

# Get orphan I-nodes in a graph.
# Parented I-nodes are the starting point of an edge towards something other than a crosslink.
# Orphans will be the collection of all other I-nodes.
def get_orphans(ibis_xaif):
    # Identify cross-links so they aren't treated as ancestry
    crosslink_node_ids = [n['nodeID'] for n in ibis_xaif['AIF']['nodes'] 
                      if n['type'] == 'MA' and n['text'] == 'Cross Link']
    non_crosslink_edges = [e for e in ibis_xaif['AIF']['edges'] 
                           if e['fromID'] not in crosslink_node_ids
                           and e['toID'] not in crosslink_node_ids]

    # Get nodes parented by something other than a crosslink: has an edge towards something other than a crosslink relation
    parented = list(set([e['fromID'] for e in non_crosslink_edges]))

    # Orphans are any I-nodes which aren't parented
    i_nodes = [n['nodeID'] for n in ibis_xaif['AIF']['nodes'] if n['type'] == 'I']
    orphans = [n_id for n_id in i_nodes if n_id not in parented]
    return orphans


# Get child I-nodes of a specific node
# Child I-nodes are the starting point of a minimal path (1 rel only) to the parent node.
def get_children(node_id, ibis_xaif):
    # Identify cross-links so they aren't treated as ancestry
    crosslink_node_ids = [n['nodeID'] for n in ibis_xaif['AIF']['nodes'] 
                      if n['type'] == 'MA' and n['text'] == 'Cross Link']

    # (Non-crosslink) relations targeting the parent
    ingoing_rel_nodes = [e['fromID'] for e in ibis_xaif['AIF']['edges'] if e['toID'] == node_id and e['fromID'] not in crosslink_node_ids]

    # Children are the origin points for these relations
    children = [e['fromID'] for e in ibis_xaif['AIF']['edges'] if e['toID'] in ingoing_rel_nodes]

    # Ensure only I-nodes are returned as children
    i_nodes = [n['nodeID'] for n in ibis_xaif['AIF']['nodes'] if n['type'] == 'I']
    children = list(set(children).intersection(i_nodes))
    return children


# Get parent I-nodes of a specific node
def get_parents(node_id, ibis_xaif):
    # Identify cross-links so they aren't treated as ancestry
    crosslink_node_ids = [n['nodeID'] for n in ibis_xaif['AIF']['nodes'] 
                      if n['type'] == 'MA' and n['text'] == 'Cross Link']

    # (Non-crosslink) relations targeting the child
    outgoing_rel_nodes = [e['toID'] for e in ibis_xaif['AIF']['edges'] if e['fromID'] == node_id and e['toID'] not in crosslink_node_ids]

    # Parents are the target points for these relations
    parents = [e['toID'] for e in ibis_xaif['AIF']['edges'] if e['fromID'] in outgoing_rel_nodes]

    # Ensure only I-nodes are returned as parents
    i_nodes = [n['nodeID'] for n in ibis_xaif['AIF']['nodes'] if n['type'] == 'I']
    parents = list(set(parents).intersection(i_nodes))
    return parents



# Get all descendants of a node
# Prevents looping, but includes self if descent is circular
def get_descendants(node_id, ibis_xaif, seen=[]):
    direct_children = get_children(node_id, ibis_xaif)
    descendants = direct_children

    for child_id in direct_children:
        if child_id not in seen:
            descendants += get_descendants(child_id, ibis_xaif, seen=seen+[node_id]+descendants)

    # Remove duplicates: an argument may be pro one position and con another
    return list(set(descendants))


# Return true if one node descends from the other
def line_of_ancestry(node1_id, node2_id, ibis_xaif):
    node1_descendants = get_descendants(node1_id, ibis_xaif)
    node2_descendants = get_descendants(node2_id, ibis_xaif)

    return node1_id in node2_descendants or node2_id in node1_descendants


#  Return true if nodes share a parent
def siblings(node1_id, node2_id, ibis_xaif):
    node1_parents = get_parents(node1_id, ibis_xaif)
    node2_parents = get_parents(node2_id, ibis_xaif)

    return bool(set(node1_parents).intersection(node2_parents))



################
# Construction #
################

def add_node(nodeID, type, text, xaif):
    n = {
        "nodeID": nodeID,
        "type": type,
        "text": text
    }
    xaif['AIF']['nodes'].append(n)
    return n

def add_edge(fromID, toID, edgeID, xaif):
    e = {
            "edgeID": edgeID,
            "fromID": fromID,
            "toID": toID
        }
    xaif['AIF']['edges'].append(e)
    return e

def anchoring_l_nodes(inodeID, xaif):
    l_node_ids = []
    node_ids_to_i = [e['fromID'] for e in xaif['AIF']['edges'] if e['toID'] == inodeID]
    ya_node_ids_to_i = [n['nodeID'] for n in xaif['AIF']['nodes'] if n['type'] == 'YA' 
                     and n['nodeID'] in node_ids_to_i]
    for ya in ya_node_ids_to_i:
        nodes_ids_to_ya = [e['fromID'] for e in xaif['AIF']['edges'] if e['toID'] == ya]
        nodes_to_ya = [n for n in xaif['AIF']['nodes'] if n['nodeID'] in nodes_ids_to_ya]
        l_node_ids_to_ya = [n['nodeID'] for n in nodes_to_ya if n['type'] == 'L']
        l_node_ids += l_node_ids_to_ya
    
    return l_node_ids


def add_s_node_with_edges(nodeID, type, text, ant_id_list, cons_id,  xaif):
    add_node(nodeID, type, text)
    
    edge_counter = max([e['edgeID'] for e in xaif['AIF']['edges']]) + 1 if len(xaif['AIF']['edges']) > 0 else 1
    add_edge(nodeID, cons_id, edge_counter, xaif)
    edge_counter += 1

    for n in ant_id_list:
        add_edge(n, nodeID, edge_counter, xaif)
        edge_counter += 1


# !! Needs a more robust way of guaranteeing unique node IDs
def add_directional_crosslink(inode_id_ant, inode_id_cons, xaif):
    # Create and add the linking relation node
    link_id = f"crosslink_{inode_id_ant}_{inode_id_cons}"
    add_node(link_id, "MA", "Cross Link", xaif)
    
    # Create and add the connecting edges between the I-nodes and the relation
    edge_counter = max([e['edgeID'] for e in xaif['AIF']['edges']]) + 1 if len(xaif['AIF']['edges']) > 0 else 1
    add_edge(inode_id_ant, link_id, edge_counter, xaif)
    edge_counter += 1
    add_edge(link_id, inode_id_cons, edge_counter, xaif)
    edge_counter += 1

    # Get all L-nodes involved in each I-node
    antecedent_anchors = anchoring_l_nodes(inode_id_ant, xaif)
    consequent_anchors = anchoring_l_nodes(inode_id_cons, xaif)
    
    # For each consequent-anchoring L-node, create a TA linking the complete
    # antecedant-anchoring L-node set to the consequent-anchoring L-node
    for cons_lnode in consequent_anchors:
        # Create the transition and anchor the link to it
        taID = f"ta_{cons_lnode}_{link_id}"
        yaID = f"ya_{taID}"
        add_node(taID, "TA", "Default Transition", xaif)
        add_node(yaID, "YA", "Default Illocution", xaif)
        add_edge(taID, yaID, edge_counter, xaif)
        edge_counter += 1
        add_edge(yaID, link_id, edge_counter, xaif)
        edge_counter += 1

        # Connect transition to its consequent 
        add_edge(taID, cons_lnode, edge_counter, xaif)
        edge_counter += 1

        # Connect transition to its antecedents
        for ant_lnode in antecedent_anchors:
            add_edge(ant_lnode, taID, edge_counter, xaif)
            edge_counter += 1





def add_crosslink(node_id_1, node_id_2, ibis_xaif):
    add_directional_crosslink(node_id_1, node_id_2, ibis_xaif)
    add_directional_crosslink(node_id_2, node_id_1, ibis_xaif)
    return ibis_xaif