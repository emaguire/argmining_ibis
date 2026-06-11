from flask import Flask, redirect, request, render_template, jsonify, render_template_string
import markdown2

import os
import sys
import subprocess
import time

import uuid
import tempfile
import shutil

import datetime
import json
from glob import glob


from app import celery_tasks
from app import xaif_dg_convert
from app import llm_caller
from app import dg_utils

# from app import intake_files
# from app import text_to_ibis
# from app import merge_ibis
# from app import crosslink_ibis
# from app import utils

import asyncio
import logging

# Check dev mode for whether to do file cleanup
DEV_MODE = os.getenv('DEV_MODE', False)

# Add logs to the docker logs
logger = logging.getLogger()
logger.setLevel(logging.INFO)
handler = logging.StreamHandler(sys.stdout)
handler.setLevel(logging.INFO)
formatter = logging.Formatter('[%(asctime)s][%(levelname)s]: %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)

# Create the flask appp
flask_app = Flask(__name__)

CONCURRENCY=4

def new_tmp_dir():
    if DEV_MODE:
        temp_dir = f"temp_{datetime.datetime.now().strftime("%y-%m-%d_%H-%M")}_{llm_caller.MODEL_NAME.split('/')[0]}"
    else:
        temp_dir = os.path.join(tempfile.gettempdir(), str(uuid.uuid4()))
    
    os.mkdir(os.path.join('temp',temp_dir))
    temp_dir = os.path.join('temp',temp_dir)
    return temp_dir


###########################
# Testing/dev entrypoints #
###########################


# Check the llm response is working
@flask_app.route('/health', methods=['GET'])
def alive():    
    return jsonify("I'm (still) alive!")

# Check the llm response is working
@flask_app.route('/test', methods=['GET'])
def test_call():    
    if DEV_MODE:
        logger.info("Container running in dev mode.")
    else:
        logger.info("Container running in normal (non-dev) mode.")
    response = llm_caller.test_llm()
    logger.info("Response type is %s", type(response))
    return jsonify(response)

# Check the llm response is working
@flask_app.route('/hello', methods=['GET'])
def say_hello():    
    if DEV_MODE:
        logger.info("Container running in dev mode.")
    else:
        logger.info("Container running in normal (non-dev) mode.")
    response = llm_caller.hello_world()
    logger.info("Response type is %s", type(response))
    return jsonify(response)

@flask_app.route('/celery-hello', methods=['GET'])
def check_model_with_celery():    
    result = celery_tasks.hello_world_llm.delay()
    return jsonify(result.get())

# Get a response from a celery worker
@flask_app.route('/celery', methods=['GET'])
def test_celery():    
    result = celery_tasks.add.delay(5,5)
    answer = result.get()
    task_id = result.id
    return jsonify(f"Task {task_id} produced this very nice answer: {answer}")

# Get a response from a celery worker using the task id
@flask_app.route('/celery-id', methods=['GET'])
def test_celery_id():    
    result = celery_tasks.add.delay(5,5)
    task_id = result.id
    result_again = celery_tasks.celery_app.AsyncResult(task_id)
    answer = result_again.get()
    return jsonify(f"Task {task_id} produced: {answer}")



# Sanity-checking test for async
@flask_app.route('/async', methods=['GET'])
async def test_async():    
    result = celery_tasks.twenty_secs.delay()
    return jsonify({'task_id': result.id})

@flask_app.route('/async-arg', methods=['GET'])
async def test_async_arg():    
    result = celery_tasks.pass_an_arg.delay("foo")
    return result.get()

@flask_app.route('/add', methods=['GET'])
async def test_add():    
    result = celery_tasks.add.delay(2,2)
    return jsonify({'task_id': result.id})

# Get a dict back for testing that json are being handled properly
@flask_app.route('/dummy', methods=['GET'])
async def test_dict():    
    result = celery_tasks.dummy_map.delay()
    return jsonify(result.get())

# An endpoint for ad hoc tests
@flask_app.route('/scratch', methods=['GET'])
async def scratch_tester():
    input_path = "./temp/temp_26-05-10_16-41_nvidia/xaifmerge_26051005164613.json"
    with open(input_path) as f:
        ibis_xaif = json.loads(f.read())
    # ibis_xaif = await merge_ibis.graft_issues(ibis_xaif)
    return jsonify(ibis_xaif)




###################
# Docs entrypoint #
###################

@flask_app.route('/', methods=['GET'])
def index():
    
    # Get the absolute path to README.md in the root directory
    readme_path = os.path.join(os.path.abspath(os.path.dirname(__file__)), '..', 'README.md')

    # Normalize the path to ensure no redundant parts
    readme_path = os.path.abspath(readme_path)

    # Read the markdown file
    with open(readme_path, 'r', encoding='utf-8') as file:
        md_content = file.read()

    # Convert to HTML
    html_content = markdown2.markdown(md_content)

    # Add CSS link
    css_link = '<link rel="stylesheet" href="https://example.com/path/to/your/styles.css">'
    html_with_css = f"<html><head>{css_link}</head><body>{html_content}</body></html>"

    # Render the HTML content as a template
    return render_template_string(html_with_css)


####################
# Celery functions #
####################

# Check the status of a celery task with the posted ID
@flask_app.route('/task-status', methods=['POST'])
def check_celery_task():
     task_id = request.form.get('id')
     result = celery_tasks.celery_app.AsyncResult(task_id)
     return jsonify({
         'task_id': task_id,
         'status': result.status
     })
    #  return jsonify(f"Status of {task_id}: {result.status}")

# Get the result of a celery task with the posted ID
@flask_app.route('/task-result', methods=['POST'])
def get_celery_task_result():
     task_id = request.form.get('id')
     result = celery_tasks.celery_app.AsyncResult(task_id)
     return jsonify(result.get())



#############################################################
# Main entrypoint: intake original files and run end-to-end #
#############################################################


# Run the whole thing end-to-end
# This needs to deal with the posted input and send it onward
# and send back a celery task id
@flask_app.route('/', methods=['POST'])
async def argmine_ibis():
    # Check input
    file_list = request.files.getlist('file')
    if not file_list:
        return jsonify({"error": "No file uploaded"}), 400  # Handle missing file

    # Make the temp dir
    temp_dir = new_tmp_dir()
    if DEV_MODE:
        with open(f"{temp_dir}/MODEL_NAME.txt", 'w') as f:
            f.write(llm_caller.MODEL_NAME)
    
    # Save the input files
    orig_dir = os.path.join(temp_dir, 'orig_files')
    os.mkdir(orig_dir)
    
    for file in file_list:
        logger.info("Read file %s", file.filename)
        short_filename = os.path.basename(file.filename)
        file.save(os.path.join(orig_dir, short_filename))

    # Give the task to the celery worker
    result = celery_tasks.argmining_complete_pipeline.delay(temp_dir)

    # Return the celery task ID
    logger.info("** Started task %s **", str(result.id))
    return jsonify({'task_id': result.id})
    



    try:
        #######################################
        # 1. Intake files and process to text #
        #######################################



        # Make copies of original input files
        orig_dir = os.path.join(temp_dir, 'orig_files')
        os.mkdir(orig_dir)
        
        for file in file_list:
            logger.info("Read file %s", file.filename)
            short_filename = os.path.basename(file.filename)
            file.save(os.path.join(orig_dir, short_filename))

        text_dir = os.path.join(temp_dir, 'input_text')
        os.mkdir(text_dir)

        # Convert input files to plaintext
        local_input_files = glob(os.path.join(orig_dir, "*"))
        logger.info('Creating texts for %s', str(local_input_files))
        try:
            text_list = intake_files.create_texts(local_input_files, chunk_size=chunk_size, save_to_dir=text_dir)
        except Exception as e:
            logger.error("Text-creation failed", exc_info=True)
        

        logger.info("!!! FILE PROCESSING DONE")

        ############################################
        # 2. Initial argmining on individual files #
        ############################################
        # For each created text chunk, create IBIS XAIF
        # Accumulate in a list of python dicts
        
        xaif_creation_tasks = []

        async def create_xaif(text, origin_name, save_to_dir):
            async with semaphore:
                return await text_to_ibis.text_to_ibis(text, origin_name=origin_name, save_to_dir=save_to_dir)

        for file_entry in text_list:
            # If only one chunk, no need to name output
            if len(file_entry['text']) == 1: 
                logger.info('Running text_to_ibis on %s', file_entry['origin'])
                try:
                    xaif_creation_tasks.append(create_xaif(file_entry['text'][0], origin_name=file_entry['origin'], save_to_dir=temp_dir))
                except Exception as e:
                    logger.error('Failed to get initial text analysis for %s', file_entry['origin'], exc_info=True)
            
            # Otherwise, give the parts numbered names
            elif len(file_entry['text']) > 1:
                counter = 0
                for chunk in file_entry['text']:
                    namesplit = file_entry['origin'].rsplit('.',1)
                    if len(namesplit) > 1:
                        chunk_name = f"{namesplit[0]}_{counter}.{namesplit[-1]}"
                    else:
                        chunk_name = f"{namesplit[0]}_{counter}"

                    logger.info('Running text_to_ibis on content from %s (part %s/%s)', chunk_name, str(counter+1), str(len(file_entry['text'])))
                    try:
                        xaif_creation_tasks.append(create_xaif(chunk, origin_name=chunk_name, save_to_dir=temp_dir))
                        logger.info("Completed for part %s", str(counter))
                    except Exception as e:
                        logger.error('Failed to get initial text analysis for %s', chunk_name, exc_info=True)
                    counter += 1
        
        xaif_list = await asyncio.gather(*xaif_creation_tasks)

        logger.info("!!! INITIAL ARGMINING ON CHUNKS DONE")


        #####################################
        # 3. Merge all resulting XAIF files #
        #####################################
        logger.info('Merging files into a single file')
        try:
            merged_xaif = merge_ibis.merge_xaif_list(xaif_list, save_to_dir=temp_dir)
        except Exception as e:
            logger.error("File merging failed", exc_info=True)

        logger.info("!!! SIMPLE FILE MERGE DONE")
        

        ##################
        # 4. Merge nodes #
        ##################
        logger.info('Merging nodes')
        try:
            merged_xaif = await merge_ibis.merge_ibis_nodes(merged_xaif, save_to_dir=temp_dir)
        except Exception as e:
            logger.error("Node merging failed", exc_info=True)

        logger.info("!!! NODE MERGING DONE")

        #################
        # 5. Link nodes #
        ################# 
        logger.info('Linking nodes')
        try:
            result_xaif = await crosslink_ibis.link_nodes(merged_xaif, save_to_dir=temp_dir)
        except Exception as e:
            result_xaif = merged_xaif
            logger.error("Node linking failed", exc_info=True)

        logger.info("!!! NODE LINKING DONE")
    
    # Clear temp directory at the end if this wasn't in devmode
    finally:
        if not DEV_MODE:
            logger.info("Cleaning up temp directory.")
            shutil.rmtree(temp_dir)
    
    logger.info("!!! Done!")

    return jsonify(result_xaif)




@flask_app.route('/convert-to-dg', methods=['POST'])
def convertor():
    if request.method == 'POST':

        logger.info("Converting file!")

        f = request.files.get('file')
        if not f:
            return jsonify({"error": "No file uploaded"}), 400  # Handle missing file

        topic = request.form.get('topic') # replace with data stream: curl -d "param1=myvalue"
        if not topic:
            return jsonify({"error": "No topic provided"}), 400  # Handle missing file

        # Generate unique filenames
        xaif_filename = f"{uuid.uuid4()}.json"
        f.save(xaif_filename)

        try:
            with open(xaif_filename, 'r') as xaif_file:
                ibis_xaif = json.load(xaif_file)  # Validate JSON format
        except json.JSONDecodeError:
            os.remove(xaif_filename)
            return jsonify({"error": "Invalid JSON format"}), 400
        
        logger.info("File loaded")

        ####################################
        
        dg_format = xaif_dg_convert.xaif_to_dg(ibis_xaif, topic)

        #####################################

        logger.info("Conversion to DG complete!")

        # Clean up the uploaded file
        os.remove(xaif_filename)

        return jsonify(dg_format)