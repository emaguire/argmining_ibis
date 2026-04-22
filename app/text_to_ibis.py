import json
import os
import datetime

from app import llm_caller
from app.utils import new_ibis_aif, add_node, add_edge

import sys
import logging 

# Add logs to the docker logs
logger = logging.getLogger()
logger.setLevel(logging.DEBUG)
handler = logging.StreamHandler(sys.stdout)
handler.setLevel(logging.DEBUG)
formatter = logging.Formatter('[%(asctime)s][%(levelname)s]: %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)


def ibis_output_to_xaif(in_dict):
    xaif = new_ibis_aif()
    all_i_node_ids = [n['id'] for n in in_dict['ibis']]
    
    edge_counter = 0
    relnode_counter = 0 
    ta_counter = 0

    i_node_anchors = {}

    # First round: create and anchor I-nodes
    for n in in_dict['ibis']:
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
        for orig in n['orig']:
            l_node = add_node(f"l_{orig_counter}_{n['id']}", 'L', orig, xaif)
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


    # Second round: create and anchor relations
    for n in in_dict['ibis']:
        if n['type'] == 'argument':
            rels_to_create = [{'id': concl_id, 'reltype': 'Pro'} for concl_id in n['pro']] + [{'id': concl_id, 'reltype': 'Con'} for concl_id in n['con']]
        elif n['type'] == 'position':
            rels_to_create = [{'id': concl_id, 'reltype': 'Position On'} for concl_id in n['parent']]
        elif n['type'] == 'issue':
            rels_to_create = [{'id': concl_id, 'reltype': 'Related Issue'} for concl_id in n['parent']]
        
        for c in rels_to_create:
            # Ensure parent node exists
            if c['id'] not in all_i_node_ids:
                continue

            # Create relation node
            relID = f"rel{relnode_counter}"
            relnode_counter += 1
            if c['reltype'] == 'Pro':
                rel_node = add_node(relID, 'RA', 'Pro', xaif)
            elif c['reltype'] == 'Con':
                rel_node = add_node(relID, 'CA', 'Con', xaif)
            else:
                rel_node = add_node(relID, 'MA', c['reltype'], xaif)

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
                ta_node = add_node(taID, "TA", "Default Transition", xaif)
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
def text_to_ibis(input_text, origin_name='', save_to_dir=''):
    if save_to_dir:
        if origin_name:
            file_base = origin_name.rsplit('.',1)[0]
        else: 
            file_base = f"unknown_{datetime.datetime.now().strftime("%y%m%d%m%H%M%S")}"
    
    result_json = llm_caller.text_to_informal_ibis(input_text)
    
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