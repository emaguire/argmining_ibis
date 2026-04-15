import json
import os
import datetime

from app import llm_caller
from app.utils import new_ibis_aif

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
    xaif_dict = new_ibis_aif()
    
    edge_counter = 0
    relnode_counter = 0

    for n in in_dict['ibis']:
        # Store IBIS and source information
        if n['type'] == 'issue':
            xaif_dict['IBIS']["issues"].append(n['id'])
        elif n['type'] == 'position':
            xaif_dict['IBIS']['positions'].append(n['id'])
        elif n['type'] == 'argument':
            xaif_dict['IBIS']['arguments'].append(n['id'])

        for orig in n['orig']:
            xaif_dict['source_info'].append({
                "nodeID": n['id'],
                "orig": orig,
                "source": ''
            })

        node = {
            "nodeID": n['id'],
            "type": 'I',
            "text": n['text']
        }

        # Add node
        xaif_dict['AIF']['nodes'].append(node)

        # Create argument nodes and edges if needed
        if n['type'] == 'argument':
            for p in n['pro']:

                # Create relation node
                relID = f"rel{relnode_counter}"
                relnode_counter += 1

                relnode = {
                    'nodeID': relID,
                    'type': 'RA',
                    'text': 'Pro'
                }
                
                xaif_dict['AIF']['nodes'].append(relnode)

                # Link it with a pair of edges
                e1 = {
                    "edgeID": edge_counter,
                    "fromID": n['id'],
                    "toID": relID
                }
                edge_counter += 1
                
                e2 = {
                    "edgeID": edge_counter,
                    "fromID": relID,
                    "toID": p
                }
                edge_counter += 1
                
                xaif_dict['AIF']['edges'] += [e1, e2]

            for p in n['con']:
                # Create relation node
                relID = f"rel{relnode_counter}"
                relnode_counter += 1

                relnode = {
                    'nodeID': relID,
                    'type': 'CA',
                    'text': 'Con'
                }
                xaif_dict['AIF']['nodes'].append(relnode)

                # Link it with a pair of edges
                e1 = {
                    "edgeID": edge_counter,
                    "fromID": n['id'],
                    "toID": relID
                }
                edge_counter += 1
                
                e2 = {
                    "edgeID": edge_counter,
                    "fromID": relID,
                    "toID": p
                }
                edge_counter += 1
                
                
                xaif_dict['AIF']['edges'] += [e1, e2]
                

        # Add MA nodes and edges
        else:
            for p in n['parent']:
                
                # Make relation node
                relID = f"rel{relnode_counter}"
                relnode_counter += 1
                relnode = {
                    'nodeID': relID,
                    'type': 'MA',
                }
                if n['type'] == 'issue':
                    relnode['text'] = 'Related Issue'
                elif n['type'] == 'position':
                    relnode['text'] = 'Position On'

                xaif_dict['AIF']['nodes'].append(relnode)

                # Link it with a pair of edges
                e1 = {
                    "edgeID": edge_counter,
                    "fromID": n['id'],
                    "toID": relID
                }
                edge_counter += 1
                
                e2 = {
                    "edgeID": edge_counter,
                    "fromID": relID,
                    "toID": p
                }
                edge_counter += 1

                xaif_dict['AIF']['edges'] += [e1, e2]
                
                
    return xaif_dict

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
    # If this had an source provided, add it as info.
    if origin_name:
        for s in xaif_output['source_info']:
            s['source'] = origin_name
    
    if save_to_dir:
        with open(os.path.join(save_to_dir, f"{file_base}_aif.json"), 'w') as f:
            json.dump(xaif_output, f, indent=4)


    return xaif_output