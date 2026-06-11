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
    # i_nodes = [n['nodeID'] for n in ibis_xaif['AIF']['nodes'] if n['type'] == 'I']
    # orphans = [n_id for n_id in i_nodes if n_id not in parented]
    i_nodes = [n for n in ibis_xaif['AIF']['nodes'] if n['type'] == 'I']
    orphans = [n for n in i_nodes if n['nodeID'] not in parented]
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


# Return list of source texts for an I-node
def get_source_texts_list(i_node_id, xaif):
    ya_node_ids = {n['nodeID']: n for n in xaif['AIF']['nodes'] if n['type'] == 'YA'}
    l_node_ids = {n['nodeID']:n for n in xaif['AIF']['nodes'] if n['type'] == 'L'}

    nodes_to_i = [e['fromID'] for e in xaif['AIF']['edges'] if e['toID'] == i_node_id]
    ya_to_i = [n for n in nodes_to_i if n in list(ya_node_ids.keys())]

    anchoring_l_ids = []
    for ya in ya_to_i:
        nodes_to_ya = [e['fromID'] for e in xaif['AIF']['edges'] if e['toID'] == ya]
        l_to_ya = [n for n in nodes_to_ya if n in l_node_ids]

        anchoring_l_ids += l_to_ya

    anchoring_l_texts = [n['text'] for n in xaif['AIF']['nodes'] if n['nodeID'] in anchoring_l_ids]
    return anchoring_l_texts

# Return a ready-formatted string
def get_source_texts(i_node_id, xaif):
    list_of_texts = get_source_texts_list(i_node_id, xaif)
    return "\n".join(list_of_texts)