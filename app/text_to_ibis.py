from google import genai

import json
import os
import datetime

from _ibis import ibis

client = genai.Client()


# !! Take IBIS type, orig out of the nodes themselves.
def output_2_xaif(in_dict):
    xaif_dict = {
        "AIF": {
            "nodes": [],
            "edges": []
        }
    }
    
    edge_counter = 0
    relnode_counter = 0

    for n in in_dict['ibis']:
        node = {
            "nodeID": n['id'],
            "type": 'I',
            "text": n['text'],
            "orig": n['orig'],
            "ibisType": n['type']
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
    prompt = f'''
    For the given input text, return a list of JSON objects of three types (issue, position, argument) based on original text spans from the text.
    Valid fields for all three types are: id, orig, text, type. The orig field contains the original text span. The text field contains the original text span rephrased as a single grammatically correct question if it was a question, or rephrased as a complete sentence otherwise.
    An example of orig and text fields is:
    {{
    "orig": "As we do not know how long the condition lasts",
    "text": "We do not know how long the condition lasts."
    }}
    Additional valid fields for objects of type 'issue' and 'position' are: parent.
    Additional valid fields for objects of type 'argument' are: pro, con.

    The types are described here:
    1. Issues. Text spans which contain the main issue or question being addressed by the text. The 'parent' field is a list with the ID of any other issue, position or argument which this issue is a question about, if any. The 'parent' field should otherwise be an empty list. Give each issue an ID in the form 'issNUMBER'.

    2. Positions. Text spans which provide answers to or ideas about the issues. The 'parent' field is a list with the ID of the issue each position is connected to. Give each position an ID in the form 'posNUMBER'. 

    3. Arguments. Text spans which give reasons for or against the positions, or for or against other arguments. The 'pro' field is a list with the ID of every position or other argument it is a pro for. The 'con' field is a list with the ID of every position or other argument it is a con for. Give each argument an ID in the form 'argNUMBER'. 

    Use UK spelling.

    Input text:
    {input_text}

    Output JSON:
    '''


    response = client.models.generate_content(
        model='gemini-3-flash-preview',
        contents=prompt,
        config={'response_mime_type': "application/json",
            'response_json_schema': ibis.model_json_schema()}
        )
    
    result_json = json.loads(response.text)
    
    xaif_output = output_2_xaif(result_json)


    # Add sourcing and save to dir if wanted

    # If this had an source provided, add it as info.
    # !! Take source info out of the nodes
    if origin_name:
        for n in xaif_output['AIF']['nodes']:
            n['source'] = [origin_name]

    if save_to_dir:
        if origin_name:
            file_base = origin_name.rsplit('.',1)[0]
        else: 
            file_base = f"unknown_{datetime.datetime.now().strftime("%y%m%d%m%H%M%S")}"

        with open(os.path.join(save_to_dir,f"{file_base}_ibisout.json"), 'w') as f:
            json.dump(result_json, f, indent=4)
        
        with open(os.path.join(save_to_dir, f"{file_base}_aif.json"), 'w') as f:
            json.dump(xaif_output, f, indent=4)


    return xaif_output