import json
import os
import datetime

from app import llm_caller
from app.utils import new_ibis_aif, add_node, add_edge

from copy import deepcopy
import sys
import logging 
import asyncio

# Add logs to the docker logs
logger = logging.getLogger()
logger.setLevel(logging.DEBUG)
handler = logging.StreamHandler(sys.stdout)
handler.setLevel(logging.DEBUG)
formatter = logging.Formatter('[%(asctime)s][%(levelname)s]: %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)


def valid_ibis_rel(child_type, parent_type):
    if child_type == 'issue' and parent_type in ['issue', 'posiiton', 'argument']:
        return True
    elif child_type == 'position' and parent_type == 'issue':
        return True
    elif child_type == 'argument' and parent_type == 'position':
        return True
    else:
        return False

# Get children by finding nodes which designate the input node as a parent, 
# and which are themselves of the right type
def get_valid_ibis_children(node, ibis_output, verbose=False):
    all_issues = [n for n in ibis_output if n['type'] == 'issue']

    if verbose:
        print(f"\nGetting valid children for node {node['id']}:")
        print(node)


    if node['type'] == 'argument': # can only have issues as children
        potential_children = all_issues
        valid_children = [n for n in potential_children if node['id'] in n['parent']]
    
    elif node['type'] == 'issue': # can have positions and other issues as children
        all_positions = [n for n in ibis_output if n['type'] == 'position']
        potential_children = all_issues + all_positions
        valid_children = [n for n in potential_children if node['id'] in n['parent']]

    elif node['type'] == 'position': # can have arguments and issues as children
        all_args  = [n for n in ibis_output if n['type'] == 'argument']
        potential_children = all_issues + all_args
        valid_arg_children = [n for n in all_args if node['id'] in n['pro'] or node['id'] in n['con']]
        valid_iss_children = [n for n in all_issues if node['id'] in n['parent']]
        valid_children = valid_arg_children + valid_iss_children

    else:
        potential_children = []
        valid_children = []

    if verbose:
        print("Pool of potential children: ", potential_children)
        print("Valid children: ", valid_children)

    return valid_children


def get_valid_ibis_descendants(node_id, nodelist, verbose=False):
    descendants = []
    immediate_children = get_valid_ibis_children(node_id, nodelist)
    if verbose:
        print(f"Immediate children of {node_id} are: {immediate_children}")
    
    descendants += immediate_children
    
    for child in immediate_children:
        if verbose:
            print(f"Getting descendants of child {child}")
        descendants += get_valid_ibis_descendants(child, nodelist)
    
    # Remove duplicates in case of an argument which is the child of more than one position
    descendants = [i for n, i in enumerate(descendants) if i not in descendants[n + 1:]]

    return descendants



def ibis_output_to_xaif(in_dict, verbose=False):
    xaif = new_ibis_aif()
    all_i_node_ids = [n['id'] for n in in_dict['ibis']]
    
    if verbose:
        print(f"===== Building valid IBIS graph =====")
    # Only keep nodes that are part of a valid structure
    # Start from top level issues, and keep their valid descendents
    all_issues = [n for n in in_dict['ibis'] if n['type'] == 'issue']
    orphan_issues = [n for n in all_issues if len(n['parent']) == 0]
    
    if verbose:
        print(f"All issues: ")
        print(all_issues)
        print(f"Orphan issues: ")
        print(orphan_issues)
    rooted_ibis = deepcopy(orphan_issues)
    
    for n in orphan_issues:
        if verbose:
            print(f"\n----- Getting valid desendents of {n} -----")
        rooted_ibis += get_valid_ibis_descendants(n, in_dict['ibis'], verbose=verbose)
    
    # Remove any duplicates (args may have multiple parents)
    rooted_ibis = [i for n, i in enumerate(rooted_ibis) if i not in rooted_ibis[n + 1:]]
    

    # Nodes were added if they had a valid parent, but arguments can have multiple parents:
    # Remove any extra invalid parents (only positions in the rooted ibis list are valid)
    args = [n for n in rooted_ibis if n['type'] == 'argument']
    pos_ids = [n['id'] for n in rooted_ibis if n['type'] == 'position']

    for a in args:
        a['pro'] = list(set(a['pro']).intersection(set(pos_ids)))
        a['con'] = list(set(a['con']).intersection(set(pos_ids)))
    rooted_ibis = [n for n in rooted_ibis if n['type'] != 'argument'] + args

    if verbose:
        print("\n==== Final list of valid nodes and relations ====")
        for n in rooted_ibis:
            print(n)

    # Convert to AIF
    edge_counter = 0
    relnode_counter = 0 
    ta_counter = 0

    i_node_anchors = {}

    # First round: create and anchor I-nodes
    if verbose:
        print("=== CREATING AND ANCHORING I-NODES ===")

    for n in rooted_ibis:
        # Store IBIS information
        if n['type'] == 'issue':
            xaif['IBIS']["issues"].append(n['id'])
        elif n['type'] == 'position':
            xaif['IBIS']['positions'].append(n['id'])
        elif n['type'] == 'argument':
            xaif['IBIS']['arguments'].append(n['id'])

        # Create and add I-node
        i_node = add_node(n['id'], 'I', n['text'], xaif)

        # Create and add L and YA nodes for each origin segment
        i_node_anchors[i_node['nodeID']] = []
        orig_counter = 0
        if verbose:
            print(f"\nAnchoring node {n['id']}! It has {len(n['orig'])} anchor(s).")
        
        for t in n['orig']:
            l_node = add_node(f"l_{orig_counter}_{n['id']}", 'L', t, xaif)
            ya_node = add_node(f"ya_{orig_counter}_{n['id']}", "YA", "Default Illocuting", xaif)
            orig_counter += 1 

            # Record the created L-node as anchor point for this I-node
            i_node_anchors[i_node['nodeID']].append(l_node['nodeID'])
        
            # Connect from L to YA
            add_edge(l_node['nodeID'],ya_node['nodeID'],edge_counter, xaif)
            edge_counter += 1

            # Connect from YA to I
            add_edge(ya_node['nodeID'],i_node['nodeID'],edge_counter, xaif)
            edge_counter += 1

            if verbose:
                print(f"\tAnchored {n['id']} origin text: {t}")
                print(f"\t\tCreated L-node {l_node} and YA-node {ya_node}")


    # Second round: create and anchor relations
    if verbose:
        print("=== CREATING AND ANCHORING RELATION NODES ===")
    # for n in in_dict['ibis']:
    for n in rooted_ibis:
        if n['type'] == 'argument':
            rels_to_create = [{'id': concl_id, 'reltype': 'Pro'} for concl_id in n['pro']] + [{'id': concl_id, 'reltype': 'Con'} for concl_id in n['con']]
        elif n['type'] == 'position':
            rels_to_create = [{'id': concl_id, 'reltype': 'Position On'} for concl_id in n['parent']]
        elif n['type'] == 'issue':
            rels_to_create = [{'id': concl_id, 'reltype': 'Related Issue'} for concl_id in n['parent']]
        
        if verbose:
            print(f"\nCreating relations for node {n['id']}")
            for r in rels_to_create:
                print(f"\t{r}")

        for c in rels_to_create:
            # Ensure parent node exists
            if c['id'] not in all_i_node_ids:
                if verbose:
                    print("No real parent for suggested relation: ", c)
                continue

            # Create relation node
            relID = f"rel{relnode_counter}"
            relnode_counter += 1
            if c['reltype'] == 'Pro':
                add_node(relID, 'RA', 'Pro', xaif)
            elif c['reltype'] == 'Con':
                add_node(relID, 'CA', 'Con', xaif)
            else:
                add_node(relID, 'MA', c['reltype'], xaif)

            # Link it to the I-nodes with a pair of edges
            add_edge(n['id'], relID, edge_counter, xaif)
            edge_counter += 1
            add_edge(relID, c['id'], edge_counter, xaif)
            edge_counter += 1


            # Create a TA for each premise-anchoring L-node, connecting it to all conclusion-anchoring L-nodes
            # Anchor the relation in each of these TAs
            for premise_l_anchor in i_node_anchors[n['id']]:
                # Create and add TA node
                taID = f"ta{ta_counter}"
                add_node(taID, "TA", "Default Transition", xaif)
                ta_counter += 1
                
                # Create and add YA node
                yaID = f"ya_{taID}"
                ya_node = add_node(yaID, "YA", "Default Illocution", xaif)

                # Connect TA to rel via YA with a pair of edges
                add_edge(taID, yaID, edge_counter, xaif)
                edge_counter += 1
                add_edge(yaID, relID, edge_counter, xaif)
                edge_counter += 1

                # Set current premise L-node as consequent of the TA
                add_edge(taID, premise_l_anchor, edge_counter, xaif)
                edge_counter += 1

                # Set all conclusion L-nodes as antecedents of the TA
                for anchoring_l in i_node_anchors[c['id']]:
                    add_edge(anchoring_l, taID, edge_counter, xaif)
                    edge_counter += 1
                
    return xaif


# Given a text, return an IBIS graph in AIF
# If given a directory to use, will save the original model output and the AIF as JSON files
async def text_to_ibis(input_text, origin_name='', save_to_dir=''):
    if save_to_dir:
        if origin_name:
            file_base = origin_name.rsplit('.',1)[0]
        else: 
            file_base = f"unknown_{datetime.datetime.now().strftime("%y%m%d%m%H%M%S")}"
    
    result_json = await llm_caller.text_to_informal_ibis(input_text)
    # result_json = await asyncio.gather(result_json_coro)
    
    logger.debug("Result of text_to_informal_ibis is type %s", type(result_json))
    if type(result_json) is str:
        logger.debug("!! Start: %s", result_json[:50])
        logger.debug("!! End: %s", result_json[-50:])


    
    if save_to_dir:
        if type(result_json) is dict:
            with open(os.path.join(save_to_dir,f"{file_base}_ibisout.json"), 'w') as f:
                json.dump(result_json, f, indent=4)
        else:
            with open(os.path.join(save_to_dir,f"{file_base}_failed_ibisout.json"), 'w') as f:
                f.write(result_json)
        

    xaif_output = ibis_output_to_xaif(result_json)

    # Add sourcing and save to dir if wanted
    l_nodes = [n for n in xaif_output['AIF']['nodes'] if n['type'] == 'L']
    if origin_name != '':
        for l in l_nodes:
            l['text'] = f"{origin_name}: {l['text']}"
    else:
        for l in l_nodes:
            l['text'] = f"Unknown: {l['text']}"
    
    if save_to_dir:
        with open(os.path.join(save_to_dir, f"{file_base}_aif.json"), 'w') as f:
            json.dump(xaif_output, f, indent=4)


    return xaif_output