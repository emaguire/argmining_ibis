import datetime
import json
import os
import sys
from copy import deepcopy
from collections import Counter

import asyncio

from pathlib import Path
from sentence_transformers import CrossEncoder


from app import llm_caller
from app.utils import new_ibis_aif, get_ibis_type, node_merge_output, get_orphans, get_children, batch_list

import logging
logging.getLogger("openai").setLevel(logging.INFO)
logger = logging.getLogger()
logger.setLevel(logging.INFO)
handler = logging.StreamHandler(sys.stdout)
handler.setLevel(logging.INFO)
formatter = logging.Formatter('[%(asctime)s][%(levelname)s]: %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)

HF_TOKEN = Path('/run/secrets/HF_KEY.txt').read_text().strip() if Path('/run/secrets/HF_KEY.txt').exists() else None
CONCURRENCY = 2

cross_enc_model = CrossEncoder("cross-encoder/stsb-roberta-base")

def test_crossencoder():
    score = cross_enc_model.predict([("Dundee is the sunniest city in Scotland.", "The children of Ulster thank you for your work.")])
    return score

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

        merged_xaif_dict['IBIS']['issues'] += current_xaif['IBIS']['issues']
        merged_xaif_dict['IBIS']['positions'] += current_xaif['IBIS']['positions']
        merged_xaif_dict['IBIS']['arguments'] += current_xaif['IBIS']['arguments']

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

# Perform node merges in the XAIF (in place)
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
        
        if verbose:
            print("Checked against original nodes: ", merger['ids'])
        
        # Remove old nodes, add new ones
        ibis_xaif['AIF']['nodes'] = [n for n in ibis_xaif['AIF']['nodes'] 
                                     if n['nodeID'] not in merger['ids']] + [new_node]
        ibis_xaif['IBIS'][f"{ibis_type}s"] = [n for n in ibis_xaif['IBIS'][f"{ibis_type}s"]
                                              if n not in merger['ids']] + [new_node['nodeID']]


        # Replace references in edges
        for e in ibis_xaif['AIF']['edges']:
            if e['toID'] in merger['ids']:
                e['toID'] = new_id
            if e['fromID'] in merger['ids']:
                e['fromID'] = new_id
        
    
    return new_id_list



# Type-specific prompts: return IDs of nodes to merge, and the text to use in the merge
async def get_issues_to_merge(issue_ids, ibis_xaif):
    input_list = [(n['nodeID'], n['text']) for n in ibis_xaif['AIF']['nodes'] if n['nodeID'] in issue_ids]
    base_merger = {'merges':[]}

    if len(input_list) < 2:
        return base_merger
    
    semaphore = asyncio.Semaphore(CONCURRENCY)
    async def get_issues_to_merge_for_batch(b):
        async with semaphore:
            return await llm_caller.issues_to_merge(b)

    issue_merger_tasks = []
    batches = batch_list(input_list)
    for b in batches:
        issue_merger_tasks.append(get_issues_to_merge_for_batch(b))
    issue_mergeset_list = await asyncio.gather(*issue_merger_tasks)
    
    for next_merge in issue_mergeset_list:
        base_merger['merges'] += next_merge['merges']
    
    return base_merger


async def get_propositions_to_merge(proposition_ids, ibis_xaif):
    input_list = [(n['nodeID'], n['text']) for n in ibis_xaif['AIF']['nodes'] if n['nodeID'] in proposition_ids]
    base_merger = {'merges':[]}    
    
    if len(input_list) < 2:
        return base_merger
    
    semaphore = asyncio.Semaphore(CONCURRENCY)
    async def get_props_to_merge_for_batch(b):
        async with semaphore:
            return await llm_caller.propositions_to_merge(b)

    prop_merger_tasks = []
    batches = batch_list(input_list)
    for b in batches:
        prop_merger_tasks.append(get_props_to_merge_for_batch(b))
    prop_mergeset_list = await asyncio.gather(*prop_merger_tasks)
    
    for next_merge in prop_mergeset_list:
        base_merger['merges'] += next_merge['merges']

    return base_merger



# Merge siblings of the same type, and apply recursively to the combined children of any resulting merges
# Check whether sibling nodes of the same type can be merged, and the same for the children of any merged nodes
# When using, start by providing the set of parentless nodes
# Happens in-place: only need what it returns if you want to do more
async def merge_siblings(sibling_ids, ibis_xaif):
    if len(sibling_ids) < 2:
        return ibis_xaif
    
    # Will want to record the IDs of the produced merge nodes, to check their new combined set of children
    new_merger_ids = []

    # Identify nodes of each IBIS type to merge among the siblings

    # Issues
    issue_siblings = [n for n in ibis_xaif['AIF']['nodes'] 
                      if n['nodeID'] in sibling_ids 
                      and n['nodeID'] in ibis_xaif['IBIS']['issues']]
    issues_to_merge = await get_issues_to_merge(issue_siblings, ibis_xaif)
    
    # Positions
    position_siblings = [n for n in ibis_xaif['AIF']['nodes'] 
                if n['nodeID'] in sibling_ids 
                and n['nodeID'] in ibis_xaif['IBIS']['positions']]
    positions_to_merge = await get_propositions_to_merge(position_siblings, ibis_xaif)

    # Arguments
    argument_siblings = [n for n in ibis_xaif['AIF']['nodes'] 
            if n['nodeID'] in sibling_ids 
            and n['nodeID'] in ibis_xaif['IBIS']['arguments']]
    arguments_to_merge = await get_propositions_to_merge(argument_siblings, ibis_xaif)
    
    # Apply merging to all identified sets of to-merge nodes, and keep the IDs of the resulting merger nodes
    new_merger_ids += merge_nodesets(issues_to_merge, ibis_xaif)
    new_merger_ids += merge_nodesets(positions_to_merge, ibis_xaif)
    new_merger_ids += merge_nodesets(arguments_to_merge, ibis_xaif)


    # Recursion: check for merging on the combined children of any merged nodes
    for new_node in new_merger_ids:
        ibis_xaif = await merge_siblings(get_children(new_node, ibis_xaif), ibis_xaif)

    return ibis_xaif



async def graft_issues(ibis_xaif, verbose=False):
    orphans = get_orphans(ibis_xaif)
    
    # Only issues should ever be orphans anyway, but check.
    orphan_issues = [n['nodeID'] for n in ibis_xaif['AIF']['nodes'] 
                     if n['nodeID'] in orphans and n['nodeID'] in ibis_xaif['IBIS']['issues']]
    
    other_issues = [n['nodeID'] for n in ibis_xaif['AIF']['nodes']
                    if n['nodeID'] in ibis_xaif['IBIS']['issues']
                    and n['nodeID'] not in orphan_issues]
    
    list_orphans = [(n['nodeID'], n['text']) for n in ibis_xaif['AIF']['nodes'] if n['nodeID'] in orphan_issues]
    list_other = [(n['nodeID'], n['text']) for n in ibis_xaif['AIF']['nodes'] if n['nodeID'] in other_issues]

    # Original batchless
    # node_merge_results = llm_caller.issues_to_merge_across_lists(list_orphans, list_other)

    semaphore = asyncio.Semaphore(CONCURRENCY)
    async def batch_issues_across_lists(list_a, list_b):
        async with semaphore:
            return await llm_caller.issues_to_merge_across_lists(list_a, list_b)

    # Commenting this section out until local permissions resolved and it can be completed
    # merger_lists = []
    orphan_batches = batch_list(list_orphans)
    other_batches = batch_list(list_other)

    cross_list_merger_tasks = []
    for orphans in orphan_batches:
        for others in other_batches:
            cross_list_merger_tasks.append(batch_issues_across_lists(orphans, others))
            # merger_lists.append(llm_caller.issues_to_merge_across_lists(orphans, others))
    
    merger_lists = await asyncio.gather(*cross_list_merger_tasks)

    # Orphans or other were empty: just return as is
    if len(merger_lists) == 0:
        return ibis_xaif
    
    # Only one set of identified merges: use as is
    elif len(merger_lists) == 1:
        node_merge_results = merger_lists[0]
    
    # Multiple sets of identified merges: combine, remove conflicting proposals
    else:
        all_merges = {'merges': [pair for mergelist in merger_lists for pair in mergelist['merges']]}

        # Split unique and conflicting merge proposals
        nodes_used_in_merges = [nodeid for pair in all_merges['merges'] for nodeid in pair['ids']]

        unique_merges = []
        contested_merges = []

        counter_nodes_used = Counter(nodes_used_in_merges)
        for merge in all_merges['merges']:
            if len(merge['ids']) == 2: # skip any misformed pairs
                if all(counter_nodes_used[nodeid] == 1 for nodeid in merge['ids']):
                    unique_merges.append(merge)
                else:
                    contested_merges.append(merge)

        # Keep any unique proposals
        node_merge_results = {'merges': unique_merges}

        # Select from among the contested merges
        all_contested_node_ids = []
        for merge in contested_merges:
            all_contested_node_ids += merge['ids']
        all_contested_node_ids = list(set(all_contested_node_ids))

        contested_complete_nodes = [n for n in ibis_xaif['AIF']['nodes'] if n['nodeID'] in all_contested_node_ids]

        # Create a dict where keys are nodeIDs and values are the text
        node_text_dict = {}
        for n in contested_complete_nodes:
            node_text_dict[n['nodeID']] = n['text']

        # Use this to create a list of text pairs corresponding to each contested merge
        text_pairs = [(node_text_dict[merge['ids'][0]], node_text_dict[merge['ids'][1]]) for merge in contested_merges]
                
        scores = cross_enc_model.predict(text_pairs)

        # Zip the merges and scores together
        ranked = []
        for z in list(zip(contested_merges, scores)):
            ranked.append({'merge': z[0], 'score': z[1]})

        # Sort from highest to lowest score
        ranked = sorted(ranked, key=lambda x: x['score'], reverse=True)

        # Work through list from highest to lowest
        # Note involvement of node in a chosen merge, skip merges where an ID has appeared in a higher-ranked merge
        resolved_ids = []
        chosen_merges = []
        for x in ranked:
            ids_considered = x['merge']['ids']
            # If neither ID used in a higher-ranked merge, keep this merge
            if not set(resolved_ids).intersection(set(ids_considered)):
                resolved_ids += ids_considered # these have now been used
                chosen_merges.append(x['merge'])
    
        node_merge_results['merges'] += chosen_merges
    
    # Can be handled the same way as other merging: merging replaces edge mentions, 
    # which will create parent relations for the orphan being merged in.
    new_merger_ids = merge_nodesets(node_merge_results, ibis_xaif, verbose=verbose)
    # Check whether you need to merge any children in the combined child sets
    for new_node in new_merger_ids:
        children = get_children(new_node, ibis_xaif)
        ibis_xaif = await merge_siblings(children, ibis_xaif)
    
    return ibis_xaif



##############
# Node merge #
##############

# Merge IBIS nodes based on structure.
# Issues may be merged if at least one has no parent
# Other nodes may only be merged if they are siblings (potentially due to merging of their parent issues)
async def merge_ibis_nodes(ibis_xaif, file_name='', save_to_dir='', verbose=False):
    # Attempt to merge orphans, recursively merge any resulting merged child sets
    ibis_xaif = await merge_siblings(get_orphans(ibis_xaif), ibis_xaif)

    # Attempt to merge remaining orphan issues with sub issues
    ibis_xaif = await graft_issues(ibis_xaif, verbose=verbose)

    if save_to_dir:
        if file_name:
            with open(os.path.join(save_to_dir, file_name), 'w') as f:
                json.dump(ibis_xaif, f, indent=4)
        else:
            with open(os.path.join(save_to_dir, f"nodemerge_{datetime.datetime.now().strftime("%y%m%d%m%H%M%S")}.json"), 'w') as f:
                json.dump(ibis_xaif, f, indent=4)
    
    return ibis_xaif