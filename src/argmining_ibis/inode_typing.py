import os
import json
import datetime
import asyncio

from .utils import batch_list
from .llm_caller import assign_question_types, assign_proposition_types

CONCURRENCY = 2


async def subtype_nodes(xaif, file_name='', save_to_dir=''):
    q_results = {"infoseekq": [], "delibq":[]}
    p_results = {"fact": [], "policy": [], "value": []}
    
    # Get all the I-nodes and prep them for being sent
    q_nodes = [n for n in xaif['AIF']['nodes'] if n['nodeID'] in xaif['IBIS']['issues']]
    p_nodes = [n for n in xaif['AIF']['nodes'] if n['nodeID'] in xaif['IBIS']['positions'] or n['nodeID'] in xaif['IBIS']['arguments']]

    q_input_list = [(n['nodeID'], n['text']) for n in q_nodes]
    p_input_list = [(n['nodeID'], n['text']) for n in p_nodes]

    # Batch em in case there's a lot of nodes
    question_batches = batch_list(q_input_list)
    proposition_batches = batch_list(p_input_list)


    # Create and run tasks for batches of questions
    semaphore = asyncio.Semaphore(CONCURRENCY)
    async def subtype_batch_of_questions(b):
        async with semaphore:
            return await assign_question_types(b)
    
    question_subtype_tasks = []
    for bq in question_batches:
        question_subtype_tasks.append(subtype_batch_of_questions(bq))
    subtyped_question_batches = await asyncio.gather(*question_subtype_tasks)


    # Create and run tasks for batches of questions
    semaphore = asyncio.Semaphore(CONCURRENCY)
    async def subtype_batch_of_propositions(b):
        async with semaphore:
            return await assign_proposition_types(b)
    
    proposition_subtype_tasks = []
    for bp in proposition_batches:
        proposition_subtype_tasks.append(subtype_batch_of_propositions(bp))
    subtyped_proposition_batches = await asyncio.gather(*proposition_subtype_tasks)


    # Merge batch results to add to the XAIF
    for q_batch_result in subtyped_question_batches:
        for k in q_results:
            if k in q_batch_result:
                q_results[k] += q_batch_result[k]

    for p_batch_result in subtyped_proposition_batches:
        for k in p_results:
            if k in p_batch_result:
                p_results[k] += p_batch_result[k]

    xaif['AIF']['propTypes'] = {}
    for k in q_results:
        xaif['AIF']['propTypes'][k] = q_results[k]
    for k in p_results:
        xaif['AIF']['propTypes'][k] = p_results[k]

    if save_to_dir:
            if file_name:
                with open(os.path.join(save_to_dir, file_name), 'w') as f:
                    json.dump(xaif, f, indent=4)
            else:
                with open(os.path.join(save_to_dir, f"nodetypes_{datetime.datetime.now().strftime("%y%m%d%m%H%M%S")}.json"), 'w') as f:
                    json.dump(xaif, f, indent=4)

    return xaif