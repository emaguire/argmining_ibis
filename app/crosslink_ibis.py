import os
import datetime
import json

import asyncio

from app import llm_caller
from app.utils import node_merge_output, siblings, line_of_ancestry, add_crosslink, batch_list

CONCURRENCY=2

async def get_issues_to_link(issue_ids, ibis_xaif, verbose=False):
    input_list = [(n['nodeID'], n['text']) for n in ibis_xaif['AIF']['nodes'] if n['nodeID'] in issue_ids]
    base_merger = {'merges':[]}

    if verbose:
        print(f"Issue IDs provided: ", issue_ids)
        print(f"Issue-linking input list: ", input_list)

    if len(input_list) < 2:
        return base_merger
    
    semaphore = asyncio.Semaphore(CONCURRENCY)
    async def get_issues_to_link_from_batch(b):
        async with semaphore:
            return await llm_caller.issues_to_link(b)

    issue_linker_tasks = []
    batches = batch_list(input_list)
    for b in batches:
        issue_linker_tasks.append(get_issues_to_link_from_batch(b))
    issue_linkset_list = await asyncio.gather(*issue_linker_tasks)
    
    for next_merge in issue_linkset_list:
        base_merger['merges'] += next_merge['merges']

    return base_merger



async def get_propositions_to_link(prop_ids, ibis_xaif, verbose=False):
    input_list = [(n['nodeID'], n['text']) for n in ibis_xaif['AIF']['nodes'] if n['nodeID'] in prop_ids]
    base_merger = {'merges':[]}

    if verbose:
        print("Proposition IDs provided: ", prop_ids)
        print(f"Proposition-linking input list: ", input_list)

    if len(input_list) < 2:
        return base_merger

    semaphore = asyncio.Semaphore(CONCURRENCY)
    async def get_props_to_link_from_batch(b):
        async with semaphore:
            return await llm_caller.propositions_to_link(b)

    prop_linker_tasks = []
    batches = batch_list(input_list)
    for b in batches:
        prop_linker_tasks.append(get_props_to_link_from_batch(b))
    prop_linkset_list = await asyncio.gather(*prop_linker_tasks)
    
    for next_merge in prop_linkset_list:
        base_merger['merges'] += next_merge['merges']

    # batches = batch_list(input_list)
    # for b in batches:
    #     next_merge = llm_caller.propositions_to_link(b)
    #     base_merger['merges'] += next_merge['merges']
    
    return base_merger




async def link_nodes(ibis_xaif, file_name='', save_to_dir='', verbose=False):
    # (only need the first item in the output of link-finding, the pair of node IDs: 
    # the second will be an empty string in this case)
    # Issues
    # all_issues = [n for n in ibis_xaif['AIF']['nodes'] if n['type'] == 'I' and n['nodeID'] in ibis_xaif['IBIS']['issues']]
    issue_link_search_result = await get_issues_to_link(ibis_xaif['IBIS']['issues'], ibis_xaif, verbose=verbose)
    if verbose:
        print("Result of issue search:", issue_link_search_result)
    possible_issues_to_link = [m['ids'] for m in issue_link_search_result['merges']]
    # Remove pairs which are direct siblings or for which one descends from the other
    issues_to_link = [i for i in possible_issues_to_link
                      if not line_of_ancestry(i[0], i[1], ibis_xaif)
                      and not siblings(i[0], i[1], ibis_xaif)]
    
    # Positions
    position_link_search_result = await get_propositions_to_link(ibis_xaif['IBIS']['positions'], ibis_xaif, verbose=verbose)
    possible_positions_to_link = [m['ids'] for m in position_link_search_result['merges']]
    # Remove pairs which are direct siblings or for which one descends from the other
    positions_to_link = [i for i in possible_positions_to_link
                      if not line_of_ancestry(i[0], i[1], ibis_xaif)
                      and not siblings(i[0], i[1], ibis_xaif)]

    # Arguments
    argument_link_search_result = await get_propositions_to_link(ibis_xaif['IBIS']['arguments'], ibis_xaif, verbose=verbose)
    possible_link_arguments = [m['ids'] for m in argument_link_search_result['merges']]
    # Remove pairs which are direct siblings or for which one descends from the other
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