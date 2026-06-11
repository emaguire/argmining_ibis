from app import dg_utils
from collections import Counter
from copy import deepcopy

################
# Quick makers #
################

def make_dg_node(id, parent, type, heading_txt, compact_txt, expanded_txt, weight=0):
    node_dict = {
        "NodeID": id,
        "ParentID": parent,
        "NodeType": type,
        "HeadingText": heading_txt,
        "CompactText": compact_txt,
        "ExpandedText": expanded_txt,
        "AvgWeight": weight
    }
    return node_dict


def make_dg_crosslink(type, source_id, target_id):
    crosslink_dict = {
        "LinkType": type,
        "SourceID": source_id,
        "DestinationID": target_id
    }
    return crosslink_dict

########
# Info #
########


def get_ibis_type(node_id, ibis_xaif):
    if node_id in ibis_xaif['IBIS']['issues']:
        return 'issue'
    elif node_id in ibis_xaif['IBIS']['positions']:
        return 'position'
    elif node_id in ibis_xaif['IBIS']['arguments']:
        return 'argument'
    else:
        return None

def get_dg_type(node_id, rel_type, ibis_xaif):
    ibis_type = get_ibis_type(node_id, ibis_xaif)
    if ibis_type == "issue":
        return "Issue"
    elif ibis_type == "position":
        return "Position"
    elif ibis_type == "argument":
        if rel_type == "RA":
            return "SupportiveArgument"
        else:
            return "OpposingArgument"
    else:
        return None

def get_dg_children(node_id, dg_graph):
    child_ids = [n for n in dg_graph["Nodes"] if n['ParentID'] == node_id]
    return child_ids

def get_dg_descendants(node_id, dg_graph):
    descendants = []
    children = get_dg_children(node_id, dg_graph)

    descendants = children
    for child_id in children:
        descendants += get_dg_children(child_id, dg_graph)
    
    return descendants


# Get next unused possible node ID in the DG graph
def next_free_id(dg_graph):
    dg_node_ids = [n['NodeID'] for n in dg_graph['Nodes']]
    next_free = max(dg_node_ids) + 1
    return next_free


# Replace all node_ids and return next free ID
def replace_ids(ibis_xaif):
    id_counter = 1

    # Replace for nodes
    for n in ibis_xaif['AIF']['nodes']:
        new_id = id_counter
        old_id = n['nodeID']
        
        n['nodeID'] = new_id

        # Replace in edges
        for e in ibis_xaif['AIF']['edges']:
            if e['fromID'] == old_id:
                e['fromID'] == new_id
            if e['toID'] == old_id:
                e['toID'] == new_id
        
        ibis_xaif['IBIS']['issues'] = [new_id if x == old_id else x for x in ibis_xaif['IBIS']['issues']]
        ibis_xaif['IBIS']['positions'] = [new_id if x == old_id else x for x in ibis_xaif['IBIS']['positions']]
        ibis_xaif['IBIS']['arguments'] = [new_id if x == old_id else x for x in ibis_xaif['IBIS']['arguments']]

        id_counter += 1
    
        # Replace for edges
        for e in ibis_xaif['AIF']['edges']:
            if e['fromID'] == old_id:
                e['fromID'] = new_id
            elif e['toID'] == old_id:
                e['toID'] = new_id


# Return nodes in XAIF linked by a relation (assuming antecedent must be an I-node)
def get_nodes_in_rel(relnode, xaif):
    i_node_ids = [n['nodeID'] for n in xaif['AIF']['nodes'] if n['type'] == 'I']
    nodes = {'ant': [], 'cons':[]}

    edges_from_rel = [e for e in xaif['AIF']['edges'] if e['fromID'] == relnode['nodeID']]
    edges_all_to_rel = [e for e in xaif['AIF']['edges'] if e['toID'] == relnode['nodeID']]
    edges_to_rel = [e for e in edges_all_to_rel if e['fromID'] in i_node_ids]

    ant_ids = [e['fromID'] for e in edges_to_rel]
    cons_ids = [e['toID'] for e in edges_from_rel]
    nodes['ant'] = [n for n in xaif['AIF']['nodes'] if n['nodeID'] in ant_ids]
    nodes['cons'] = [n for n in xaif['AIF']['nodes'] if n['nodeID'] in cons_ids]
    nodes['rel'] = relnode

    return nodes


# Return a list of crosslinked nodes in the form
# [{'ant': [id1], 'cons': [id2]}, ...]
def get_all_crosslinks(xaif):
    cl_nodes = [n for n in xaif['AIF']['nodes'] if n['text'] == 'Cross Link' and n['type'] == 'MA']

    linked_by_cl = []
    for cl in cl_nodes:
        linked_by_cl.append(get_nodes_in_rel(cl, xaif))
    
    return linked_by_cl





##########
# Update #
##########

def new_branch_from_node(parent_old_id, parent_new_id, dg_dict):
    # Find children related under the old ID
    children = get_dg_children(parent_old_id, dg_dict)

    # Replicate the family structure with new node entries
    for child in children:
        # Make a record of the old ID so you can find its children later
        old_child_id = child["NodeID"]
        new_child_id = next_free_id(dg_dict)
        
        # Make a copy of the child with a new ID, and attach it to the new parent
        new_child = deepcopy(child)
        new_child["NodeID"] = new_child_id
        new_child["ParentID"] = parent_new_id
        dg_dict['Nodes'].append(new_child)

        
        # Make a copy of any branches underneath and attach them to the new child
        new_branch_from_node(old_child_id, new_child_id, dg_dict)


# Find all cases of nodes where ID is duplicated: 
def resolve_duplicates(dg_dict):
    # Get current duplicates
    nodecounter = Counter([n['NodeID'] for n in dg_dict['Nodes']])
    duplicate_ids = [node_id for node_id in nodecounter if nodecounter[node_id] > 1]

    # If none, finish
    if len(duplicate_ids) == 0:
        return dg_dict

    # Otherwise get the duplicated node IDs for processing
    duplicate_nodes = {}
    for node_id in duplicate_ids:
        duplicate_nodes[node_id] = [n for n in dg_dict['Nodes'] if n['NodeID'] == node_id]

    for duplicated_id in duplicate_nodes:
        # Leave first copy alone
        other_copies = duplicate_nodes[duplicated_id][1:]
        
        # For all others, replace the ID and recreate the structure below as attached to the new ID
        for copy in other_copies:
            # Replace ID
            new_id = next_free_id(dg_dict)
            copy['NodeID'] = new_id

            # Find descendants of original node, make a copy of this under the new ID
            new_branch_from_node(duplicated_id, new_id, dg_dict)


    # Check again
    # resolve_duplicates(dg_dict)



def xaif_to_dg(ibis_xaif, topic):
    # Setup
    dg_dict = {
        "Nodes": [],
        "Crosslinks": []
    }
    topic_node = make_dg_node(0, -1, "Map", topic, '', '', 0)
    dg_dict["Nodes"].append(topic_node)
    replace_ids(ibis_xaif)

    # Attach the top-level issues to the topic
    roots = dg_utils.get_orphans(ibis_xaif)
    for node in roots:
        source_texts = dg_utils.get_source_texts(node['nodeID'], ibis_xaif)
        new_node = make_dg_node(node['nodeID'], 0, "Issue", node['text'], node['text'], source_texts)
        dg_dict['Nodes'].append(new_node)


    # Create crosslinks (simply for now)
    all_crosslinks = get_all_crosslinks(ibis_xaif)
    for link in all_crosslinks:
        for a in link['ant']:
            for c in link['cons']:
                dg_dict['Crosslinks'].append(make_dg_crosslink("Variant", a['nodeID'], c['nodeID']))


    # Create nodes: create a child node for every attachment
    all_non_cl_rels = [n for n in ibis_xaif['AIF']['nodes'] if n['type'] in ['RA', 'CA', 'MA'] and n['text'] != "Cross Link"]
    for rel in all_non_cl_rels:
        nodes_in_rel = get_nodes_in_rel(rel, ibis_xaif)

        for ant in nodes_in_rel['ant']:
            source_texts = dg_utils.get_source_texts(ant['nodeID'], ibis_xaif)
            dg_node_type = get_dg_type(ant['nodeID'], nodes_in_rel['rel']['type'], ibis_xaif)
            for cons in nodes_in_rel['cons']:
                new_node = make_dg_node(ant['nodeID'], cons['nodeID'], dg_node_type, ant['text'],ant['text'], source_texts)
                dg_dict["Nodes"].append(new_node)

    # Turn any duplicate IDs into different branches
    resolve_duplicates(dg_dict)

    # TODO: Also duplicate crosslinkage

    return dg_dict