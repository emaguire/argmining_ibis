# from google import genai

import datetime
import json
import os

from copy import deepcopy
from utils import new_ibis_aif, get_ibis_type, node_merge_output, get_orphans, get_children

# client = genai.Client()



################
# File merging #
################

# Combine multiple IBIS XAIF dicts into one.
def merge_xaif_list(xaif_list, file_name='', save_to_dir=''):
    merged_xaif_dict = new_ibis_aif()

    for i, current_xaif in enumerate(xaif_list):
        # with open(input_path) as f:
            # current_aif = json.loads(f.read())

        # Core
        for n in current_xaif['AIF']['nodes']:
            old_id = n['nodeID']
            n['nodeID'] = f"{old_id}_{i}"
            # n['source'] = [os.path.basename(input_path)]

        # Seems silly to go through the edges separately, but it might actually
        # be more sensible than searching for all relevant edges every time you update a node.
        for e in current_xaif['AIF']['edges']:
            old_from_id = e['fromID']
            old_to_id = e['toID']
            e['fromID'] = f"{old_from_id}_{i}"
            e['toID'] = f"{old_to_id}_{i}"

        merged_xaif_dict['AIF']['nodes'] += current_xaif['AIF']['nodes']
        merged_xaif_dict['AIF']['edges'] += current_xaif['AIF']['edges']

        # Doing this 
        for t in ['issues', 'positions', 'arguments']:
            current_xaif['IBIS'][t] = [f"{old_id}_{i}" for old_id in current_xaif['IBIS'][t]]
        for entry in current_xaif['source_info']:
            old_id = entry['nodeID']
            entry['nodeID'] = f"{old_id}_{i}"

        merged_xaif_dict['IBIS']['issues'] += current_xaif['IBIS']['issues']
        merged_xaif_dict['IBIS']['positions'] += current_xaif['IBIS']['positions']
        merged_xaif_dict['IBIS']['arguments'] += current_xaif['IBIS']['arguments']
        try:
            merged_xaif_dict['source_info'] += current_xaif['source_info']
        except KeyError:
            print("No source field.")

    for j, e in enumerate(merged_xaif_dict['AIF']['edges']):
        e['edgeID'] = j


    if save_to_dir:
        if file_name:
            with open(os.path.join(save_to_dir, file_name), 'w') as f:
                json.dump(merged_xaif_dict, f, indent=4)
        else:
            with open(os.path.join(save_to_dir, f"xaifmerge_{datetime.datetime.now().strftime("%y%m%d%m%H%M%S")}.json"), 'w') as f:
                json.dump(merged_xaif_dict, f, indent=4)
    
    return merged_xaif_dict


##########################
# Utils for node merging #
##########################

# Perform node merges in the XAIF
# Return a list of the IDs of the newly-created merger nodes.
def merge_nodesets(node_merge_results, ibis_xaif, verbose=False):
    new_id_list = []

    if verbose:
        print(f"Merging nodesets:", node_merge_results)

    for merger in node_merge_results['merges']:
        if verbose:
            print(f"Currently merging nodeset:", merger)

        nodes_to_merge = [n for n in ibis_xaif['AIF']['nodes'] if n['nodeID'] in merger['ids']]
        
        if verbose:
            print(f"\tOriginal nodes:", nodes_to_merge)

        new_id = "merge_" + '_'.join(merger['ids'])
        new_id_list += [new_id]
        
        # Use an original node as foundation
        new_node = deepcopy(nodes_to_merge[0])
        ibis_type = get_ibis_type(new_node['nodeID'], ibis_xaif)

        # Initialise the new values
        new_node['nodeID'] = new_id
        new_node['text'] = merger['text']
        
        # Replace ID in sources
        source_info = [s for s in ibis_xaif['source_info'] if s['nodeID'] in merger['ids']]
        for s in source_info:
            s['nodeID'] = new_id
        if verbose:
            print("Checked against original nodes: ", merger['ids'])
            print("New addition to source info: ", source_info)
        # ibis_xaif['source_info'] += source_info
        
        # Remove old nodes, add new ones
        ibis_xaif['AIF']['nodes'] = [n for n in ibis_xaif['AIF']['nodes'] 
                                     if n['nodeID'] not in merger['ids']] + [new_node]
        ibis_xaif['IBIS'][f"{ibis_type}s"] = [n for n in ibis_xaif['IBIS'][f"{ibis_type}s"]
                                              if n not in merger['ids']] + [new_node['nodeID']]
        ibis_xaif['source_info'] = [s for s in ibis_xaif['source_info'] 
                                    if s['nodeID'] not in merger['ids']]


        # Replace references in edges
        for e in ibis_xaif['AIF']['edges']:
            if e['toID'] in merger['ids']:
                e['toID'] = new_id
            if e['fromID'] in merger['ids']:
                e['fromID'] = new_id
        
    
    return new_id_list



# Type-specific prompts: return IDs of nodes to merge, and the text to use in the merge
def get_issues_to_merge(issue_ids, ibis_xaif):

    input_list = [(n['nodeID'], n['text']) for n in ibis_xaif['AIF']['nodes'] if n['nodeID'] in issue_ids]
    
    if len(input_list) < 2:
        return {'merges':[]}

    prompt = f'''
For the given input list of questions with ID codes, identify which subsets of questions, if any, can be merged.
Questions can be merged if they have the same or almost identical meaning.
The subsets must be exclusive, with no question appearing in more than one subset.
It is possible that there are no questions which can be merged.
For each subset, return a tuple with a list of the ID codes of questions in the set, and text paraphrasing the combined questions.


Example input:
[('id1', "What should we do about the park?"), ('id2', "What should happen with the park?"), ('id3', "Should a new playground be added to the park?")]

Example output:
[(['id1', 'id2'], "What should be done about the park?")]

Input list:
{input_list}

Output list:
'''
    
    response = client.models.generate_content(
    model='gemini-3-flash-preview',
    contents=prompt,
    config={'response_mime_type': "application/json",
        'response_json_schema': node_merge_output.model_json_schema()}
    )

    return json.loads(response.text)


def get_propositions_to_merge(proposition_ids, ibis_xaif):

    input_list = [(n['nodeID'], n['text']) for n in ibis_xaif['AIF']['nodes'] if n['nodeID'] in proposition_ids]
    
    if len(input_list) < 2:
        return {'merges':[]}

    prompt = f'''
For the given input list of statements with ID codes, identify which subsets of statements, if any, can be merged.
Statements can be merged if they have the same or almost identical meaning.
The subsets must be exclusive, with no statement appearing in more than one subset.
It is possible that there are no statements which can be merged.
For each subset, return a tuple with a list of the ID codes of statements in the set, and text paraphrasing the combined statements.


Example input:
[('id1', "It would be good to have more benches."), ('id2', "There should be a playground."), ('id3', "There need to be more places to sit.")]

Example output:
[(['id1', 'id3'], "There should be more seating.")]


Example input:
[('id4', "People love crocodiles."), ('id5', "Crocodiles are so cool."), ('id6', "Crocodiles could attack people.")]

Example output:
[(['id4', 'id5'], "People love crocodiles.")]


Input list:
{input_list}

Output list:
'''
    
    response = client.models.generate_content(
    model='gemini-3-flash-preview',
    contents=prompt,
    config={'response_mime_type': "application/json",
        'response_json_schema': node_merge_output.model_json_schema()}
    )

    return json.loads(response.text)



# Merge siblings of the same type, and apply recursively to the combined children of any resulting merges
# Check whether sibling nodes of the same type can be merged, and the same for the children of any merged nodes
# When using, start by providing the set of parentless nodes
def merge_siblings(sibling_ids, ibis_xaif):
    if len(sibling_ids) < 2:
        return ibis_xaif
    
    # Will want to record the IDs of the produced merge nodes, to check their new combined set of children
    new_merger_ids = []

    # Identify nodes of each IBIS type to merge among the siblings

    # Issues

    issue_siblings = [n for n in ibis_xaif['AIF']['nodes'] 
                      if n['nodeID'] in sibling_ids 
                      and n['nodeID'] in ibis_xaif['IBIS']['issues']]
    issues_to_merge = get_issues_to_merge(issue_siblings, ibis_xaif)
    
    # Positions
    position_siblings = [n for n in ibis_xaif['AIF']['nodes'] 
                if n['nodeID'] in sibling_ids 
                and n['nodeID'] in ibis_xaif['IBIS']['positions']]
    positions_to_merge = get_propositions_to_merge(position_siblings, ibis_xaif)
    

    # Arguments
    argument_siblings = [n for n in ibis_xaif['AIF']['nodes'] 
            if n['nodeID'] in sibling_ids 
            and n['nodeID'] in ibis_xaif['IBIS']['arguments']]
    arguments_to_merge = get_propositions_to_merge(argument_siblings, ibis_xaif)
    
    
    # Apply merging to all identified sets of to-merge nodes, and keep the IDs of the resulting merger nodes
    new_merger_ids += merge_nodesets(issues_to_merge, ibis_xaif)
    new_merger_ids += merge_nodesets(positions_to_merge, ibis_xaif)
    new_merger_ids += merge_nodesets(arguments_to_merge, ibis_xaif)


    # Recursion: check for merging on the combined children of any merged nodes
    for new_node in new_merger_ids:
        merge_siblings(get_children(new_node, ibis_xaif), ibis_xaif)

    return ibis_xaif



def graft_issues(ibis_xaif, verbose=False):
    orphans = get_orphans(ibis_xaif)
    
    # Only issues should ever be orphans anyway, but check.
    orphan_issues = [n['nodeID'] for n in ibis_xaif['AIF']['nodes'] 
                     if n['nodeID'] in orphans and n['nodeID'] in ibis_xaif['IBIS']['issues']]
    
    other_issues = [n['nodeID'] for n in ibis_xaif['AIF']['nodes']
                    if n['nodeID'] in ibis_xaif['IBIS']['issues']
                    and n['nodeID'] not in orphan_issues]
    
    list_orphans = [(n['nodeID'], n['text']) for n in ibis_xaif['AIF']['nodes'] if n['nodeID'] in orphan_issues]
    list_other = [(n['nodeID'], n['text']) for n in ibis_xaif['AIF']['nodes'] if n['nodeID'] in other_issues]

    prompt = f'''
You will be given two lists of questions with ID codes, List A and List B.
For the given lists, identify which pairs of questions, one from List A and one from List B, can be merged, if any.
Questions can be merged if they have the same or almost identical meaning.
The pairs must be exclusive, with no question being used in more than one pair.
It is possible that there are no question pairs which can be merged.
For each pair, return a tuple with a list of the ID codes of the questions in the pair (the ID from List A and then the ID from List B), and text paraphrasing the combined questions.


Example input 1:
LIST A:
[('id1', "What should we do about the park?"), 
('id2', "What should happen with the park?")]

LIST B:
[('id3', "Should a new playground be added to the park?")]

Example output 1:
[]


Example input 2:
LIST A:
[('id4', "What should we do about the park?")]

LIST B:
[('id5', "What should happen with the park?"),
('id6', "Should a new playground be added to the park?")]

Example output 1:
[(['id4', 'id5'], "What should be done about the park?")]


Input lists:
LIST A:
{list_orphans}

LIST B:
{list_other}

Output list:
'''
    
    response = client.models.generate_content(
    model='gemini-3-flash-preview',
    contents=prompt,
    config={'response_mime_type': "application/json",
        'response_json_schema': node_merge_output.model_json_schema()}
    )

    node_merge_results = json.loads(response.text)

    # Can be handled the same way as other merging: merging replaces edge mentions, 
    # which will create parent relations for the orphan being merged in.
    new_merger_ids = merge_nodesets(node_merge_results, ibis_xaif, verbose=verbose)
    # Check whether you need to merge any children in the combined child sets
    for new_node in new_merger_ids:
        merge_siblings(get_children(new_node, ibis_xaif), ibis_xaif)
    
    return ibis_xaif



##############
# Node merge #
##############

# Merge IBIS nodes based on structure.
# Issues may be merged if at least one has no parent
# Other nodes may only be merged if they are siblings (potentially due to merging of their parent issues)
def merge_ibis_nodes(ibis_xaif, file_name='', save_to_dir='', verbose=False):
    # Attempt to merge orphans, recursively merge any resulting merged child sets
    ibis_xaif = merge_siblings(get_orphans(ibis_xaif), ibis_xaif)

    # Attempt to merge remaining orphan issues with sub issues
    ibis_xaif = graft_issues(ibis_xaif, verbose=verbose)

    if save_to_dir:
        if file_name:
            with open(os.path.join(save_to_dir, file_name), 'w') as f:
                json.dump(ibis_xaif, f, indent=4)
        else:
            with open(os.path.join(save_to_dir, f"nodemerge_{datetime.datetime.now().strftime("%y%m%d%m%H%M%S")}.json"), 'w') as f:
                json.dump(ibis_xaif, f, indent=4)
    
    return ibis_xaif