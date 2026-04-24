import os
import sys
from pathlib import Path
import json

import instructor
from pydantic import BaseModel
from typing import List

from app.utils import node_merge_output
from app.ibis import ibis


from openai import AsyncOpenAI, OpenAI, BadRequestError
import tiktoken
import asyncio

import logging
logging.getLogger("openai").setLevel(logging.INFO)

logger = logging.getLogger()
logger.setLevel(logging.DEBUG)
handler = logging.StreamHandler(sys.stdout)
handler.setLevel(logging.DEBUG)
formatter = logging.Formatter('[%(asctime)s][%(levelname)s]: %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)

#########
# SETUP #
#########

# LLM_URL = os.getenv('LLM_URL', 'http://localhost:8000') # internal port is 8000, only use this if you've linked the containers
LLM_URL = os.getenv('LLM_URL', 'http://localhost:7060')
LLM_API_KEY = Path('/run/secrets/LLM_API_KEY.txt').read_text().strip() if Path('/run/secrets/LLM_API_KEY.txt').exists() else None
MODEL_NAME = 'meta-llama/Llama-3.2-3B-Instruct' #'google/gemma-3-4b-pt' #'swiss-ai/Apertus-8B-Instruct-2509'

# should have asyncio if you're going to do async
unstructured_client = None
structured_client = None
if LLM_API_KEY:
    client = OpenAI(
        base_url=f"{LLM_URL}/v1",
        api_key=LLM_API_KEY,
        max_retries=5,
        timeout=180.0
    )

    structured_client = instructor.from_openai(OpenAI(
        base_url=f"{LLM_URL}/v1",
        api_key=LLM_API_KEY),
        mode=instructor.Mode.JSON)


# A silly test that requires no input to check the call is working
# def test_llm(model_name="Qwen/Qwen3-4B"):
def test_llm(model_name=MODEL_NAME):
    print("Container-internal tester.")
    print(model_name)
    print("LLM_URL: ", LLM_URL)

    class Dogprice(BaseModel):
            name: str
            price: float
    class DogpriceList(BaseModel):
        dogs: List[Dogprice]
        
    
    test_client = OpenAI(
        base_url=f"{LLM_URL}/v1",
        api_key=LLM_API_KEY
    )

    prompt = '''
Output how much dogs cost using JSON. 

INPUT: One dog is a pomeranian called Kiwi and it costs €1200. Another dog is a mix called Spigot worth €20. There is also a dog named Supremo who is €10000.

OUTPUT:
'''

    messages = [
        {
            'role': 'user',
            'content': prompt
        }
    ]

    response = test_client.chat.completions.create(
                model=model_name,
                messages=[{"role": msg['role'], "content": msg['content']} for msg in messages],
                extra_body={"guided_json": DogpriceList.model_json_schema()}
            )
    
    return json.loads(response.choices[0].message.content)

# A similar silly test, but checking the instructor client is working
def test_instructor(model_name=MODEL_NAME):
    print("Container-internal tester for Instructor client.")
    print("LLM_URL: ", LLM_URL)

    class Dogprice(BaseModel):
            name: str
            price: float
    class DogpriceList(BaseModel):
        dogs: List[Dogprice]
    
    output_format = DogpriceList
    
    client = instructor.from_openai(OpenAI(
        base_url=f"{LLM_URL}/v1",
        api_key=LLM_API_KEY),
        mode=instructor.Mode.JSON)

    prompt = '''
Output how much dogs cost using JSON. 

INPUT: One dog is a pomeranian called Kiwi and it costs €1200. Another dog is a mix called Spigot worth €20. There is also a dog named Supremo who is €10000.

OUTPUT:
'''

    messages = [
        {
            'role': 'user',
            'content': prompt
        }
    ]

    try:
        # response = client.create(
        #                 model=model_name,
        #                 messages=[{"role": msg['role'], "content": msg['content']} for msg in messages],
        #                 response_model=output_format,
        #                 max_retries=1,
        #                 timeout=1200
        #             )

        user, completion = client.create_with_completion(
            model=model_name,
            response_model=output_format,
            max_retries=1,
            messages=[{"role": msg['role'], "content": msg['content']} for msg in messages],
            )
        
        print("USER")
        print(user)
        print("COMPLETION")
        print(completion)
        print("CONTENT")
        print(completion.choices[0].message.content)
        
        # return response.model_dump()
        return json.loads(completion.choices[0].message.content)
    
    except instructor.core.exceptions.InstructorRetryException as e:
        for attempt in e.failed_attempts:
            logger.info("FAILED ATTEMPT STUFF!!!")
            print(attempt)
    
    return "Oh well"



def instruct_call_llm(messages, output_format=None, model_name="swiss-ai/Apertus-8B-Instruct-2509"):
    if output_format:
        logger.debug("Structured output requested for model output: %s", output_format)
        try:
            response = structured_client.create(
                    model=model_name,
                    messages=[{"role": msg['role'], "content": msg['content']} for msg in messages],
                    response_model=output_format,
                    timeout=1200,
                    max_retries=1
                )
            response_content = response.model_dump()
        except Exception as e:
            logging.info("!!! Failed structured output !!!")
            for attempt in e.failed_attempts:
                logging.info("Here's the attempt...")
                logging.info(str(attempt))
                logging.info("Alas.")


    else:
        logger.debug("No structured output format requested for model output")
        response = unstructured_client.chat.completions.create(
                    model=model_name,
                    messages=[{"role": msg['role'], "content": msg['content']} for msg in messages],
                    timeout=1200
                )
        response_content = response.choices[0].message.content


    # logger.debug(logger.debug("Original output is type %s", type(response_content)))

    return response_content

    # have to see what happens when instructor fails to add some logging in that case
    if output_format:
        try:
            # logger.debug("Requested output format was %s", output_format)
            if type(response_content) is str:
                # logger.debug("Loading string response as json")
                json_out = json.loads(response_content)
                # logger.debug("Result of json.loads is type %s", type(json_out))
                return json_out
            else:
                logger.debug("Response can't be loaded by json.loads() because it's %s", type(response_content))
                return response_content
        except json.decoder.JSONDecodeError as e:
            logger.error("Attempted to load output as json but failed")
            logger.error("================================================")
            logger.error("Output that could not be converted by json.loads(): ")
            logger.error(response_content)
            logger.error("================================================")
            return response_content
    
    return response_content


# Returns a JSON dict as output if an output_format is specified, and a string otherwise
# Original version using pydantic, but not instructor.
# def call_llm(messages, output_format=None, model_name="Qwen/Qwen3-4B"):
def call_llm(messages, output_format=None, model_name=MODEL_NAME):
    if output_format:
        # logger.debug("Structured output requested for model output: %s", output_format)
        response = client.chat.completions.create(
                    model=model_name,
                    messages=[{"role": msg['role'], "content": msg['content']} for msg in messages],
                    extra_body={"guided_json": output_format.model_json_schema()},
                    timeout=180
                )
    else:
        # logger.debug("No structured output format requested for model output")
        response = unstructured_client.chat.completions.create(
                    model=model_name,
                    messages=[{"role": msg['role'], "content": msg['content']} for msg in messages],
                    timeout=120
                )
    
    response_content = response.choices[0].message.content

    # logger.debug(logger.debug("Original output is type %s", type(response_content)))

    if output_format:
        try:
            # logger.debug("Requested output format was %s", output_format)
            if type(response_content) is str:
                # logger.debug("Loading string response as json")
                json_out = json.loads(response_content)
                # logger.debug("Result of json.loads is type %s", type(json_out))
                return json_out
            else:
                logger.debug("Response can't be loaded by json.loads() because it's %s", type(response_content))
                return response_content
        except json.decoder.JSONDecodeError as e:
            logger.error("Attempted to load output as json but failed")
            logger.error("================================================")
            logger.error("Output that could not be converted by json.loads(): ")
            logger.error(response_content)
            logger.error("================================================")
            return response_content
    
    return response_content



############
# BATCHING #
############

# Return a list of lists: each list can be used as the input for a request.
def split_list(input_list):
    pass
    


#########
# CALLS #
#########


# Find in text

def text_to_informal_ibis(input_text):
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

    messages = [{'role': 'user', 'content': prompt}]
    result = call_llm(messages, ibis)

    return result


# Linking

def propositions_to_link(input_list):

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
[(['arg10', 'arg3'], ""),
(['arg3', 'arg12'], "")]


Input list:
{input_list}

Output list:
'''
    messages = [{'role': 'user', 'content': prompt}]
    result = call_llm(messages, node_merge_output)
    
    return result


def issues_to_link(input_list):

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

    messages = [{'role': 'user', 'content': prompt}]
    result = call_llm(messages, node_merge_output)
    
    return result 



# Merging

def propositions_to_merge(input_list):
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
    
    messages = [{'role': 'user', 'content': prompt}]
    result = call_llm(messages, node_merge_output)
    
    return result


def issues_to_merge(input_list):
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
    
    messages = [{'role': 'user', 'content': prompt}]
    result = call_llm(messages, node_merge_output)
    
    return result


def issues_to_merge_across_lists(input_list_a, input_list_b):
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
{input_list_a}

LIST B:
{input_list_b}

Output list:
'''
    
    messages = [{'role': 'user', 'content': prompt}]
    result = call_llm(messages, node_merge_output)
    
    return result