from google import genai

import os
import datetime
import json

from utils import node_merge_output, siblings, line_of_ancestry, add_crosslink

client = genai.Client()


def get_issues_to_link(issue_list, ibis_xaif, verbose=False):
    issue_ids = [n['nodeID'] for n in issue_list]
    input_list = [(n['nodeID'], n['text']) for n in ibis_xaif['AIF']['nodes'] if n['nodeID'] in issue_ids]

    if verbose:
        print(f"Issue IDs provided: ", issue_ids)
        print(f"Issue-linking input list: ", input_list)

    if len(input_list) < 2:
        return {'merges':[]}

    prompt = f'''
For the given input list of questions with ID codes, identify which pairs of questions, if any, can be closely linked.
Questions can be linked if they have the same or almost identical meaning, or if answering one provides a partial answer to the other.
Questions can appear in more than one pair.
It is possible that there are no questions which can be linked.
For each pair, return a tuple with a list of the ID codes of questions in the pair, and an empty string.


Example input:
[('id1', "What should we do about the park?"), 
('id3', "Should a new playground be added to the park?"),
('id9', "Do many children live nearby?"),
('id10', "Do many dog owners use the park?")
]

Example output:
[(['id1', 'id3'], ""),
(['id3', 'id9'], ""),]

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



def get_propositions_to_link(prop_list, ibis_xaif, verbose=False):
    prop_ids = [n['nodeID'] for n in prop_list]
    input_list = [(n['nodeID'], n['text']) for n in ibis_xaif['AIF']['nodes'] if n['nodeID'] in prop_ids]

    if verbose:
        print("Proposition IDs provided: ", prop_ids)
        print(f"Proposition-linking input list: ", input_list)

    if len(input_list) < 2:
        return {'merges':[]}
    
    prompt = f'''
For the given input list of statements with ID codes, identify which pairs of statements, if any, can be closely linked.
Statements can be linked if they have the same or almost identical meaning, if one is a generalisation of the other, or if one provides an example of the other.
Statements can appear in more than one pair.
It is possible that there are no statements which can be linked.
For each subset, return a tuple with a list of the ID codes of statements in the pair, and an empty string.


Example input 1:
[('id1', "It would be good to have more benches."), ('id2', "There should be a playground."), ('id3', "There need to be more places to sit.")]

Example output 1:
[(['id1', 'id3'], "")]


Example input 2:
[('arg10', "Breakfast clubs improve academic performance."),
('arg2', "Free meals reduce financial burdens on parents."),
('arg3', "Children do better at school when there are breakfast clubs."),
('arg8', "The budget for extra services is extremely limited."),
('arg12', "72% of primary schools participating in a breakfast club programme in south Ayrshire saw increased attendance levels.")]

Example output 2:
[(['arg10', 'arg3'], ''),
(['arg3', 'arg12'], '')]


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




def link_nodes(ibis_xaif, file_name='', save_to_dir='', verbose=False):
    # (only need the first item in the output of link-finding, the pair of node IDs: 
    # the second will be an empty string in this case)
    # Issues
    all_issues = [n for n in ibis_xaif['AIF']['nodes'] if n['type'] == 'I' and n['ibisType'] == 'issue']
    issue_search_result = get_issues_to_link(all_issues, ibis_xaif, verbose=verbose)
    if verbose:
        print("Result of issue search:", issue_search_result)
    possible_issues_to_link = [m['ids'] for m in issue_search_result['merges']]

    # Remove pairs for which one descends from the other or which are direct siblings
    issues_to_link = [i for i in possible_issues_to_link
                      if not line_of_ancestry(i[0], i[1], ibis_xaif)
                      and not siblings(i[0], i[1], ibis_xaif)]
    
    # Positions
    all_positions = [n for n in ibis_xaif['AIF']['nodes'] if n['type'] == 'I' and n['ibisType'] == 'position']
    possible_positions_to_link = [m['ids'] for m in get_propositions_to_link(all_positions, ibis_xaif, verbose=verbose)['merges']]
    # Remove pairs for which one descends from the other or which are direct siblings
    positions_to_link = [i for i in possible_positions_to_link
                      if not line_of_ancestry(i[0], i[1], ibis_xaif)
                      and not siblings(i[0], i[1], ibis_xaif)]

    # Arguments
    all_arguments = [n for n in ibis_xaif['AIF']['nodes'] if n['type'] == 'I' and n['ibisType'] == 'argument']
    possible_link_arguments = [m['ids'] for m in get_propositions_to_link(all_arguments, ibis_xaif)['merges']]
    # Remove pairs for which one descends from the other or which are direct siblings
    arguments_to_link = [i for i in possible_link_arguments
                      if not line_of_ancestry(i[0], i[1], ibis_xaif)
                      and not siblings(i[0], i[1], ibis_xaif)]
    
    for pair in issues_to_link + positions_to_link + arguments_to_link:
        ibis_xaif = add_crosslink(pair[0], pair[1], ibis_xaif)
    
    if save_to_dir:
        if file_name:
            with open(os.path.join(save_to_dir, file_name), 'w') as f:
                json.dump(ibis_xaif, f, indent=4)
        else:
            with open(os.path.join(save_to_dir, f"crosslink_{datetime.datetime.now().strftime("%y%m%d%m%H%M%S")}.json"), 'w') as f:
                json.dump(ibis_xaif, f, indent=4)

    return ibis_xaif