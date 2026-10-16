import os
import json
import datetime

from . import llm_caller
from . import utils

# Util for issue reduction: get list of top level issues for an ibis xaif
def top_level_issues(xaif):
    issues = [n for n in xaif['AIF']['nodes'] if n['nodeID'] in xaif['IBIS']['issues']]
    
    # Top-level issues will have no out-going edges, only incoming edges from a YA-node or a relation node connecting an IBIS child node
    top_issues = []
    for i in issues:
        outgoing_edges = [e for e in xaif['AIF']['edges'] if e['fromID'] == i['nodeID']]
        if len(outgoing_edges) == 0:
            top_issues += [i]
    return top_issues




###################
# Issue reduction #
###################

async def reduce_issues(input_list, max_n):
    max_n = max(max_n,1)
    
    prompt = f'''   
For the given input list of questions with ID codes, attempt to group them into at most {max_n} distinct subgroups. Do this by identifying and creating over-arching PARENT QUESTIONS that each subsubgroup helps to address. The questions in the subgroup should addressing aspects of the same over-arching PARENT QUESTIONS.

The subsets must be exclusive, with no question appearing in more than one subset.
The parent question of each group must be distinct questions.

It is possible that there are no questions which can be grouped, or are questions which cannot be included in a group with any other questions.
If a question cannot be included in the same group as other questions, it should be excluded instead of being put in a group by itself.

For each subset, return a tuple with a list of the ID codes of questions in the set, and text of the PARENT QUESTION.
Use UK spelling.


Example input 1:
[('id1', "What should we do about the park?"), ('id2', "What should happen with the park?"), ('id3', "Should a new playground be added to the park?"), ('id4', "Are there enough schools in the area?"),('id5', "Is the waste management system fit for purpose?"), ('id6', "How can young people be supported to develop skills?")]

Example output 1:
[(['id1', 'id2'], "What should be done about the park?")]
[(['id3', 'id4', 'id6'], "How can the area meet the needs of children and young people?")]



Input list:
{input_list}

Output list:
'''

    messages = [{'role': 'user', 'content': prompt}]
    result = await llm_caller.call_llm(messages, utils.node_merge_output)

    return result


async def condense_top_issues(xaif, max_issues=5):
    top_issues = top_level_issues(xaif)
    issues_to_group = []
    for i in top_issues:
        issues_to_group += (i['nodeID'], i['text'])

    condensed_issue_output = await reduce_issues(issues_to_group, max_issues)
    
    groups_to_make = [m for m in condensed_issue_output['merges'] if len(m['ids']) > 1]

    for group in groups_to_make:
    # Create the new parent node
        parent_id = '_'.join(['parent'] + [child_id for child_id in group['ids']])
        parent_issue = {
            "nodeID": parent_id,
            "type": "I",
            "text": group['text']
        }
        # Add it to XAIF in the node list and list of issues
        xaif['AIF']['nodes'].append(parent_issue)
        xaif['IBIS']['issues'].append(parent_issue['nodeID'])
        
        # Gather all contributing L-nodes
        contributing_l_nodes = []
        
        # Attach child nodes and keep track of their sources
        for child_id in group['ids']:
            contributing_l_nodes += utils.anchoring_l_nodes(child_id, xaif)
            print(f"Current contirbuting l-nodes: {contributing_l_nodes}")

            # Create and add a relation node to attach the child as a related issue
            relation_id = f"rel_subq_{child_id}"
            utils.add_s_node_with_edges(relation_id, "MA", "Related Issue", [child_id], parent_id, xaif)

        # Anchor the summarising parent node in the sources of all the child nodes it was derived from
        for k, l_node_id in enumerate(contributing_l_nodes):
            utils.add_s_node_with_edges(f"ya_{k}_{parent_id}", "YA", "Default Illocuting", [l_node_id], parent_id, xaif)
    
    return xaif



async def condense_ibis(xaif, file_name='', save_to_dir=''):
    xaif = await condense_top_issues(xaif)

    if save_to_dir:
        if file_name:
            with open(os.path.join(save_to_dir, file_name), 'w') as f:
                json.dump(xaif, f, indent=4)
        else:
            with open(os.path.join(save_to_dir, f"condensed_{datetime.datetime.now().strftime("%y%m%d%m%H%M%S")}.json"), 'w') as f:
                json.dump(xaif, f, indent=4)

    return xaif