import json
import os
import datetime
import re
from copy import deepcopy
import sys
import logging 
import asyncio

from markdown_it import MarkdownIt

from . import llm_caller
from .utils import new_ibis_aif, add_node, add_edge

# Add logs to the docker logs
logger = logging.getLogger()
logger.setLevel(logging.DEBUG)
handler = logging.StreamHandler(sys.stdout)
handler.setLevel(logging.DEBUG)
formatter = logging.Formatter('[%(asctime)s][%(levelname)s]: %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)


######################
# Utils for sourcing #
######################


def number_lines(orig_md_lines):
    numbered_lines = []
    for i, line in enumerate(orig_md_lines):
        # numbered_lines += [f'<{i}> {line}']
        if line != '\n':
            numbered_lines += [f'<{i}> {line}']
        else:
            numbered_lines += [line]
    md_numbered = '\n'.join(numbered_lines)
    return md_numbered

# part no. can be identified in `text_to_ibis` which is the parent function,
# and passed in to this one to complete the stamp
def stamp_sources(informal_ibis,numbered_source, part_no=''):
    source_lines = numbered_source.split('\n')

    # Go through each source for each node
    # Add the source's ID stamp to the end of the line it matches
    for node in informal_ibis['ibis']:
        for i, orig in enumerate(node['orig']):
            # Make the stamp for this quote
            stamp = f"<IBIS_SRC_l_{i}_{node['id']}"
            if part_no != '':
                stamp = stamp + f'_{part_no}>'
            else:
                stamp = stamp + '>'
            
            # When a line begins with the source marker, add the stamp to the end
            for j,l in enumerate(source_lines):
                result = re.match(f"{orig['src']}", l)
                if result:
                    # print(f"Found it in this line: \n\t", l)
                    source_lines[j] = l + stamp
                    # print(l)
    
    # When all nodes have had their stamps added to the lines
    # clean up by removing initial marker and rejoining them
    clean_lines = [re.sub(r'^<[\d]+>','',l).strip() for l in source_lines]
            
    return '\n'.join(clean_lines)


# Return string with the section the quote string is found in, assuming tokens
# is a markdown parse by markdown_it
def locate_quote(quote, tokens):
    found = False
    # Search for the match
    for i, target_token in enumerate(tokens):
        if quote in target_token.content:
            found = True
            break
    if not found:
        return "UNKNOWN"


    # print(f"Found target in token {i}:")
    # print(target_token.content)
    # print()

    # Start the location report. Two cases:
    # 1. Match is itself a section heading: it is its own structure info
    # (note that this means you want the marker to be something you can parse out, so you can mark and then clean a heading)
    if re.match(r'h[\d]+', target_token.tag):
        have_level = True
        position_info = target_token.content
        last_level = int(re.match(r'(?<=h)[\d]+', target_token.tag).group(0))

    # 2. Match is in some kind of text: 
    else:
        have_level = False
        position_info = ''

    # Backtrack until you reach a H1 tag or the start of the document,
    # adding higher level section names to position info as you go
    reversed_tokens = list(reversed(tokens[:i]))
    for j, token in enumerate(reversed_tokens):
        # Found a heading tag
        if re.match(r'h[\d]+', token.tag) and token.type=='heading_close':
            # print(f"found a {re.match(r'h[\d]+', token.tag).group(0)} heading")
            
            # If it's the first level we've found, take it
            # (text will be next inline element)
            if not have_level:
                have_level = True
                last_level = int(re.search(r'(?<=h)[\d]+', token.tag).group(0)) 
                # Add this heading to the position info
                position_info = reversed_tokens[j+1].content + '\n' + position_info
                
                # Update most recent level
                last_level = int(re.search(r'(?<=h)[\d]+', token.tag).group(0))

                # Finish immediately if you've found a H1
                if last_level < 2:
                    break
            
            # If a level has been found, check if it's a higher level than the most recently added heading
            # (text will be next inline element)
            elif int(re.search(r'(?<=h)[\d]+', token.tag).group(0)) < last_level:
                # Add this heading to the position info
                position_info = reversed_tokens[j+1].content + '\n' + position_info
                
                # Update most recent level
                last_level = int(re.search(r'(?<=h)[\d]+', token.tag).group(0))

                # Finish immediately if you've found a H1
                if last_level < 2:
                    break

    # Remove any stamps
    position_info = re.sub(r"<IBIS_SRC_[\w]+_[\d]+_[\w]+>",'',position_info)

    return position_info




def valid_ibis_rel(child_type, parent_type):
    if child_type == 'issue' and parent_type in ['issue', 'posiiton', 'argument']:
        return True
    elif child_type == 'position' and parent_type == 'issue':
        return True
    elif child_type == 'argument' and parent_type == 'position':
        return True
    else:
        return False



###############################################
# Utils for manipulating informal ibis output #
###############################################

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



##################
# Main functions #
##################


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
        
        for orig in n['orig']:
            t = orig['quote']
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


# Add locution and speaker fields to all xaif with location info 
def add_sources_to_xaif(xaif, full_text):
    md = MarkdownIt()
    tokens = md.parse(full_text)

    nodes_at_locations = {}
    
    # Get source locations of all l-nodes
    l_nodes = [n for n in xaif['AIF']['nodes'] if n['type'] == 'L']
    for l in l_nodes:
        node_id = l['nodeID']
        filename = l['text'].split(':')[0].strip()
        location = locate_quote(f"<IBIS_SRC_{node_id}>", tokens).strip()
        
        full_location = f"{filename}\n{location}"

        if full_location not in nodes_at_locations:
            nodes_at_locations[full_location] = {
                'nodes':[node_id],
                'file': filename,
                'location': location
                }
        else:
            nodes_at_locations[full_location]['nodes'] += [node_id]

    # Create a participant for each location and associate each locution with that ID
    participants = []
    locutions = []
    for i, loc in enumerate(nodes_at_locations):
        participants += [{
            "participantID": i + 1,
            "firstname": nodes_at_locations[loc]['file'],
            "surname":  nodes_at_locations[loc]['location']
        }]

        for n in nodes_at_locations[loc]['nodes']:
            locutions += [{
                "nodeID": n,
                "personID": i + 1,
                "start": None,
                "end": None
            }]

    xaif['AIF']['participants'] = participants
    xaif['AIF']['locutions'] = locutions

    return xaif
    


# Given a text, return an IBIS graph in AIF
# If given a directory to use, will save the original model output and the AIF as JSON files
async def text_to_ibis(input_text, topic, origin_name='', doc_source=False, save_to_dir=''):
    if save_to_dir:
        if origin_name:
            file_base_incl_number = origin_name.rsplit('.',1)[0]
        else: 
            file_base_incl_number = f"unknown_{datetime.datetime.now().strftime("%y%m%d%m%H%M%S")}"

    # Check if this is a chunk: if so, get the number
    if origin_name:
        part_match = re.search(r"(?<=_CHUNK_)[\d+](?=.txt)", origin_name)
        if part_match:
            part_no = part_match.group(0)
        else:
            part_no = ''

    # Add line numbers
    numbered_text = number_lines(input_text.split('\n'))
    result_json = await llm_caller.text_to_informal_ibis(topic, numbered_text)
    # result_json = await asyncio.gather(result_json_coro)
    # Update the copy of the text with sourcing stamps
    if doc_source:
        text_with_node_stamps = stamp_sources(result_json, numbered_text, part_no)
    
    logger.debug("Result of text_to_informal_ibis is type %s", type(result_json))
    if type(result_json) is str:
        logger.debug("!! Start: %s", result_json[:50])
        logger.debug("!! End: %s", result_json[-50:])


    
    if save_to_dir:
        if type(result_json) is dict:
            with open(os.path.join(save_to_dir,f"{file_base_incl_number}_ibisout.json"), 'w') as f:
                json.dump(result_json, f, indent=4)
        else:
            with open(os.path.join(save_to_dir,f"{file_base_incl_number}_failed_ibisout.json"), 'w') as f:
                f.write(result_json)
        

    xaif_output = ibis_output_to_xaif(result_json)

    # Add sourcing and save to dir if wanted
    l_nodes = [n for n in xaif_output['AIF']['nodes'] if n['type'] == 'L']
    if origin_name != '':
        # Remove chunk indicator if present
        file_name = re.sub(r'_CHUNK_[\d]+','', origin_name)
        for l in l_nodes:
            l['text'] = f"{file_name}: {l['text']}"
    else:
        for l in l_nodes:
            l['text'] = f"Unknown: {l['text']}"
    
    if save_to_dir:
        with open(os.path.join(save_to_dir, f"{file_base_incl_number}_aif.json"), 'w') as f:
            json.dump(xaif_output, f, indent=4)

    if doc_source:
        return xaif_output, text_with_node_stamps
    else:
        return xaif_output