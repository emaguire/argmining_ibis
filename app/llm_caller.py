import os
import sys
import re
from pathlib import Path
import json

import instructor
from pydantic import BaseModel
from typing import List
from retrying import retry

from app.utils import node_merge_output
from app.ibis import ibis


from openai import AsyncOpenAI, OpenAI, BadRequestError
import tiktoken
import asyncio

import logging
logging.getLogger("openai").setLevel(logging.INFO)

logger = logging.getLogger()
logger.setLevel(logging.INFO)
handler = logging.StreamHandler(sys.stdout)
handler.setLevel(logging.INFO)
formatter = logging.Formatter('[%(asctime)s][%(levelname)s]: %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)

#########
# SETUP #
#########

LLM_URL = os.getenv('LLM_URL', 'http://localhost:7060')
LLM_API_KEY = Path('/run/secrets/LLM_API_KEY.txt').read_text().strip() if Path('/run/secrets/LLM_API_KEY.txt').exists() else os.getenv('LLM_API_KEY')
# LLM_API_KEY = Path('./.secrets/LLM_API_KEY.txt').read_text().strip() if Path('./.secrets/LLM_API_KEY.txt').exists() else None
MODEL_NAME = os.getenv('MODEL_NAME', 'nvidia/Gemma-4-31B-IT-NVFP4')


structured_client = None
if LLM_API_KEY:
    client = AsyncOpenAI(
        base_url=f"{LLM_URL}/v1",
        api_key=LLM_API_KEY,
        max_retries=3,
        timeout=60.0
    )

else:
    logger.info("NO API KEY FOUND!!")


def get_final(response, structured=True):
    if not structured:
        to_return = response.choices[0].message.content
    
    else:
        try: 
            to_return = json.loads(response.choices[0].message.content)
            logger.info("Result loaded as JSON")
            logger.info("Starts with: %s", response.choices[0].message.content[:50])

        except:
            to_return = response.choices[0].message.content
            logger.info("Failed to load as JSON!!")
            logger.info("TOTAL RESULT: ")
            logger.info(str(response.choices[0].message.content))
            logger.info("Starts with: %s", response.choices[0].message.content[:25])

    print("Returning a result of type ", type(to_return))
    print(to_return)
    

    return to_return


def hello_world():
    client = OpenAI(
        base_url=f"{LLM_URL}/v1",
        api_key=LLM_API_KEY
    )

    prompt = "Say: hello world!"

    messages = [
        {
            'role': 'user',
            'content': prompt
        }
    ]

    response = client.chat.completions.parse(
                model=MODEL_NAME,
                messages=[{"role": msg['role'], "content": msg['content']} for msg in messages]
            )
    
    to_return = get_final(response)
    return to_return



# A silly test that requires no input to check the call is working and producing structured output
def test_llm(model_name=MODEL_NAME):
    print("Container-internal tester.")
    print(model_name)
    print("LLM_URL: ", LLM_URL)
    print("API KEY:", LLM_API_KEY)

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

    response = test_client.chat.completions.parse(
                model=model_name,
                messages=[{"role": msg['role'], "content": msg['content']} for msg in messages],
                response_format=DogpriceList
            )
    
    to_return = get_final(response)
    return to_return


# A set of functions based on the above to test that async is working
async def doggies(model_name=MODEL_NAME, dog_select=0):
    class Dogprice(BaseModel):
            name: str
            price: float
    class DogpriceList(BaseModel):
        dogs: List[Dogprice]
    
    test_client = AsyncOpenAI(
        base_url=f"{LLM_URL}/v1",
        api_key=LLM_API_KEY
    )

    doggies = ["One dog is a pomeranian called Kiwi and it costs €1200.",
               "Another dog is a mix called Spigot worth €20.",
               "There is also a dog named Supremo who is €10000.",
               "Bella the Chow Chow is a liberated canine that somehow costs nothing at all.",
               "Fido is going for €50.",
               "Lucky is a black labrador for €150"
               ]
    
    prompt = f'''
Output how much dogs cost using JSON. 

INPUT: {doggies[dog_select]}

OUTPUT:
'''

    messages = [
        {
            'role': 'user',
            'content': prompt
        }
    ]

    response = await test_client.chat.completions.parse(
                model=model_name,
                messages=[{"role": msg['role'], "content": msg['content']} for msg in messages],
                # extra_body={"guided_json": DogpriceList.model_json_schema()}
                response_format=DogpriceList
            )
    
    print("RESPONSE: ", response.choices[0].message.content)

    to_return = get_final(response)
    
    return to_return

# Use the above the test async across multible calls
async def test_llm_split(model_name=MODEL_NAME, dog_select=0):
    print("Container-internal tester.")
    print(model_name)
    print("LLM_URL: ", LLM_URL)
    print(f"!! Selecting dog numero {dog_select}")
        
    to_return = await doggies(MODEL_NAME,dog_select)
    print("Here's the result inside the llm-caller function after awaiting the function that actually contains the call: ", to_return)
    
    return to_return

# Self-contained async test
async def test_llm_async(model_name=MODEL_NAME):
    print("Container-internal tester.")
    print(model_name)
    print("LLM_URL: ", LLM_URL)

    class Dogprice(BaseModel):
            name: str
            price: float
    class DogpriceList(BaseModel):
        dogs: List[Dogprice]
        
    
    test_client = AsyncOpenAI(
        base_url=f"{LLM_URL}/v1",
        api_key=LLM_API_KEY
    )

    prompts = []
    prompts.append('''
Output how much dogs cost using JSON. 
INPUT: One dog is a pomeranian called Kiwi and it costs €1200. 
OUTPUT:''')
    prompts.append('''
Output how much dogs cost using JSON. 
INPUT: Another dog is a mix called Spigot worth €20.
OUTPUT:''')
#     prompts.append('''
# Output how much dogs cost using JSON. 
# INPUT: There is also a dog named Supremo who is €10000.
# OUTPUT:''')

    messages = [
        {
            'role': 'user',
            'content': prompt
        } for prompt in prompts
    ]

    responses = await test_client.chat.completions.create(
                model=model_name,
                messages=[{"role": msg['role'], "content": msg['content']} for msg in messages],
                # extra_body={"guided_json": DogpriceList.model_json_schema()}
                response_format=DogpriceList
            )
    
    to_return = []
    for response in responses:
        logger.info("A response item in the list: ")
        logger.info(str(response))
        to_return.append(get_final(response))
    return to_return



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


# Performs the call with retries
@retry(stop_max_attempt_number=5, wait_fixed=2000)
async def make_call_with_retry(messages, output_format=None, model_name=MODEL_NAME):
    if output_format:
        logger.info("Making call...")
        logger.debug("Structured output requested for model output: %s", output_format)

        response = await client.chat.completions.parse(
                    model=model_name,
                    messages=[{"role": msg['role'], "content": msg['content']} for msg in messages],
                    response_format=output_format,
                    timeout=120
                )
    else:
        # logger.debug("No structured output format requested for model output")
        logger.info("Making call with no structure required for output...")
        response = await client.chat.completions.create(
                    model=model_name,
                    messages=[{"role": msg['role'], "content": msg['content']} for msg in messages],
                    timeout=120
                )
    
    logger.info("Response recieved")
    logger.info("%s", response)
    response_content = response.choices[0].message.content
    # logger.debug(logger.debug("Original output is type %s", type(response_content)))

    if output_format:
        try:
            logger.debug("Requested output format was %s", output_format)
            if type(response_content) is str:
                response_content = get_final(response)
            else:
                logger.debug("Response can't be loaded by json.loads() because it's type %s", type(response_content))
        except json.decoder.JSONDecodeError as e:
            logger.error("Attempted to load output as json but failed")
            logger.error("================================================")
            logger.error("Output that could not be converted by json.loads(): ")
            logger.error(response_content)
            logger.error("================================================")
    
    return response_content


# Returns a JSON dict as output if an output_format is specified, and a string otherwise
# It fails even after internal retries, return an empty instance of the format requested
async def call_llm(messages, output_format=None, model_name=MODEL_NAME):
    try:
        response_content = await make_call_with_retry(messages, output_format, model_name)
    except Exception as e:
        logger.error("Retries failed")
        if output_format is not None:
            empty_ex = output_format()
            response_content = empty_ex.model_dump()
        else:
            response_content = ''
    
    return response_content



#########
# CALLS #
#########


# Find in text
async def text_to_informal_ibis(input_text):
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

    logger.info("Running on text beginning with: %s", input_text[:100])

    messages = [{'role': 'user', 'content': prompt}]
    result = await call_llm(messages, ibis)

    return result


# Linking

async def propositions_to_link(input_list):

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
    result = await call_llm(messages, node_merge_output)
    
    return result


async def issues_to_link(input_list):

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
    result = await call_llm(messages, node_merge_output)
    
    return result 



# Merging

async def propositions_to_merge(input_list):
    prompt = f'''
For the given input list of statements with ID codes, identify which subsets of statements, if any, can be merged.
Statements can be merged if they have the same or almost identical meaning.
The subsets must be exclusive, with no statement appearing in more than one subset.
It is possible that there are no statements which can be merged.
For each subset, return a tuple with a list of the ID codes of statements in the set, and text paraphrasing the combined statements.
Use UK spelling.


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
    result = await call_llm(messages, node_merge_output)
    
    return result


async def issues_to_merge(input_list):
    prompt = f'''
For the given input list of questions with ID codes, identify which subsets of questions, if any, can be merged.
Questions can be merged if they have the same or almost identical meaning.
The subsets must be exclusive, with no question appearing in more than one subset.
It is possible that there are no questions which can be merged.
For each subset, return a tuple with a list of the ID codes of questions in the set, and text paraphrasing the combined questions.
Use UK spelling.


Example input 1:
[('id1', "What should we do about the park?"), ('id2', "What should happen with the park?"), ('id3', "Should a new playground be added to the park?"), ('id4', "What is the best plan for the park?")]

Example output 1:
[(['id1', 'id2', 'id4'], "What should be done about the park?")]



Input list:
{input_list}

Output list:
'''
    
    messages = [{'role': 'user', 'content': prompt}]
    result = await call_llm(messages, node_merge_output)
    
    return result


async def issues_to_merge_across_lists(input_list_a, input_list_b):
    prompt = f'''
You will be given two lists of questions with ID codes, List A and List B.
For the given lists, identify which pairs of questions, one from List A and one from List B, can be merged, if any.
Questions can be merged if they have the same or almost identical meaning.
The pairs must be exclusive, with no question being used in more than one pair.
It is possible that there are no question pairs which can be merged.
For each pair, return a tuple with a list of the ID codes of the questions in the pair (the ID from List A and then the ID from List B), and text paraphrasing the combined questions.
Use UK spelling.


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
    result = await call_llm(messages, node_merge_output)
    
    return result