import os
import datetime
import json

from app import llm_caller
from app.utils import node_merge_output, siblings, line_of_ancestry, add_crosslink



def get_issues_to_link(issue_ids, ibis_xaif, verbose=False):
    input_list = [(n['nodeID'], n['text']) for n in ibis_xaif['AIF']['nodes'] if n['nodeID'] in issue_ids]

    if verbose:
        print(f"Issue IDs provided: ", issue_ids)
        print(f"Issue-linking input list: ", input_list)

    if len(input_list) < 2:
        return {'merges':[]}

    return llm_caller.issues_to_link(input_list)



def get_propositions_to_link(prop_ids, ibis_xaif, verbose=False):
    input_list = [(n['nodeID'], n['text']) for n in ibis_xaif['AIF']['nodes'] if n['nodeID'] in prop_ids]

    if verbose:
        print("Proposition IDs provided: ", prop_ids)
        print(f"Proposition-linking input list: ", input_list)

    if len(input_list) < 2:
        return {'merges':[]}
    
    return llm_caller.propositions_to_link(input_list)




def link_nodes(ibis_xaif, file_name='', save_to_dir='', verbose=False):
    # (only need the first item in the output of link-finding, the pair of node IDs: 
    # the second will be an empty string in this case)
    # Issues
    # all_issues = [n for n in ibis_xaif['AIF']['nodes'] if n['type'] == 'I' and n['nodeID'] in ibis_xaif['IBIS']['issues']]
    issue_search_result = get_issues_to_link(ibis_xaif['IBIS']['issues'], ibis_xaif, verbose=verbose)
    if verbose:
        print("Result of issue search:", issue_search_result)
    possible_issues_to_link = [m['ids'] for m in issue_search_result['merges']]

    # Remove pairs for which one descends from the other or which are direct siblings
    issues_to_link = [i for i in possible_issues_to_link
                      if not line_of_ancestry(i[0], i[1], ibis_xaif)
                      and not siblings(i[0], i[1], ibis_xaif)]
    
    # Positions
    # all_positions = [n for n in ibis_xaif['AIF']['nodes'] if n['type'] == 'I' and n['nodeID'] in ibis_xaif['IBIS']['positions']]
    possible_positions_to_link = [m['ids'] for m in get_propositions_to_link(ibis_xaif['IBIS']['positions'], ibis_xaif, verbose=verbose)['merges']]
    # Remove pairs for which one descends from the other or which are direct siblings
    positions_to_link = [i for i in possible_positions_to_link
                      if not line_of_ancestry(i[0], i[1], ibis_xaif)
                      and not siblings(i[0], i[1], ibis_xaif)]

    # Arguments
    # all_arguments = [n for n in ibis_xaif['AIF']['nodes'] if n['type'] == 'I' and n['nodeID'] in ibis_xaif['IBIS']['arguments']]
    possible_link_arguments = [m['ids'] for m in get_propositions_to_link(ibis_xaif['IBIS']['arguments'], ibis_xaif)['merges']]
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