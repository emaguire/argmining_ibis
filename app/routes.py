from flask import Flask, redirect, request, render_template, jsonify, render_template_string
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import markdown2

import os
import sys
import subprocess
from pathlib import Path

import uuid
import tempfile
import shutil

import datetime
import time
import json
from glob import glob


from app import celery_tasks
from app import xaif_dg_convert
from app import llm_caller

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

limiter = Limiter(
    get_remote_address,
    app=flask_app,
    default_limits=[],
    storage_uri="memory://",
    strategy='moving-window',
)


CONCURRENCY=4


###########################
# Testing/dev entrypoints #
###########################

# Check components are working (container itself, LLM access, celery)
######

# Check the container is responding
@flask_app.route('/health', methods=['GET'])
def alive():
    return jsonify(f"I'm (still) alive!")


@flask_app.route('/llm', methods=['GET'])
def check_llm():
    llm_url =  os.getenv('LLM_URL', 'unknown')
    # llm_url =  os.getenv('LLM_URL', 'http://localhost:7060')
    model_name = os.getenv('MODEL_NAME', 'unknown')
    # model_name = os.getenv('MODEL_NAME', 'nvidia/Gemma-4-31B-IT-NVFP4')

    return jsonify(f"Accessing model {model_name} at: {llm_url}")


# Check the llm response is working with structured output
@flask_app.route('/test', methods=['GET'])
def test_call():    
    if DEV_MODE:
        logger.info("Container running in dev mode.")
    else:
        logger.info("Container running in normal (non-dev) mode.")
    response = llm_caller.test_llm()
    logger.info("Response type is %s", type(response))
    return jsonify(response)


# Check the llm response is working even more simply
@flask_app.route('/hello', methods=['GET'])
def say_hello():    
    if DEV_MODE:
        logger.info("Container running in dev mode.")
    else:
        logger.info("Container running in normal (non-dev) mode.")
    response = llm_caller.hello_world()
    logger.info("Response type is %s", type(response))
    return jsonify(response)

# Check llm response is working from a celery worker
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


# PHP post testing endpoints
########

@flask_app.route('/php', methods=['POST'])
async def test_php():
    file_names = []
    files = request.files.to_dict()

    print(files)

    temp_dir = new_tmp_dir()
    orig_dir = os.path.join(temp_dir, 'orig_files')
    os.mkdir(orig_dir)

    for file in files:
        logger.info("file=%s", str(file))
        file_names += [{'filename':files[file].filename, 'type': str(type(files[file]))}]
        short_filename = os.path.basename(files[file].filename)
        files[file].save(os.path.join(orig_dir, short_filename))

    return jsonify(file_names)


@flask_app.route('/php-list', methods=['POST'])
async def test_php_list():
    file_names = []
    files = request.files.getlist('file[]')

    logger.info(str(type(files)))
    logger.info(str(type(files[0])))

    temp_dir = new_tmp_dir()
    orig_dir = os.path.join(temp_dir, 'orig_files')
    os.mkdir(orig_dir)

    for file in files:
        file_names += [{'filename':file.filename, 'type': str(type(file))}]
        short_filename = os.path.basename(file.filename)
        file.save(os.path.join(orig_dir, short_filename))

    return jsonify(file_names)


# Testing the rate limiter
########
@flask_app.route("/slow")
@limiter.limit("1 per day")
def slow():
    return ":(\n"


@flask_app.route("/medium")
@limiter.limit("1/second", override_defaults=False)
def medium():
    return ":|\n"


@flask_app.route("/fast")
def fast():
    return ":)\n"


@flask_app.route("/ping")
@limiter.exempt
def ping():
    return "PONG\n"


# Additional checks for celery workers
########

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
    result = celery_tasks.dummy_json.delay()
    return jsonify(result.get())





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


#########
# Utils #
#########

def new_tmp_dir(task_id=''):
    if DEV_MODE:
        if task_id=='':
            temp_dir = f"temp_{datetime.datetime.now().strftime("%y-%m-%d_%H-%M")}_{llm_caller.MODEL_NAME.split('/')[0]}"
        else:
            temp_dir = f"temp_{datetime.datetime.now().strftime("%y-%m-%d_%H-%M")}_{llm_caller.MODEL_NAME.split('/')[0]}_{task_id}"
    else:
        if task_id=='':
            temp_dir = os.path.join(tempfile.gettempdir(), str(uuid.uuid4()))
        else:
            temp_dir = os.path.join(tempfile.gettempdir(), str(task_id))
    
    os.mkdir(os.path.join('temp',temp_dir))
    temp_dir = os.path.join('temp',temp_dir)

    return temp_dir




####################
# Celery functions #
####################

# Check the status of a celery task with the posted ID
@flask_app.route('/task-status', methods=['POST'])
def check_celery_task():
     task_id = request.form.get('id')
     result = celery_tasks.celery_app.AsyncResult(task_id)
     status = result.status
     if status == 'SUCCESS':
        logger.info("TASK COMPLETE (%s): %s"%(task_id, datetime.datetime.now().strftime("%y-%m-%d_%H:%M:%S")))
     return jsonify({
         'task_id': task_id,
         'status': result.status
     })

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
@limiter.limit("100 per day;10 per 15 minutes")
async def argmine_ibis_celery():
    use_cache = os.getenv('ARGMINE_CACHE', False)
    if use_cache:
        logger.info('Using cached results where possible')
    
    # Check input
    # file_list = request.files.getlist('file')
    file_dict = request.files.to_dict()

    if not file_dict:
        return jsonify({"error": "No file uploaded"}), 400  # Handle missing file

    # Make the temp dir
    temp_dir = new_tmp_dir()
    if DEV_MODE:
        with open(f"{temp_dir}/MODEL_NAME.txt", 'w') as f:
            f.write(llm_caller.MODEL_NAME)
    
    # Save the input files
    orig_dir = os.path.join(temp_dir, 'orig_files')
    os.mkdir(orig_dir)
    
    for file in file_dict:
        logger.info("Read file %s", file_dict[file].filename)
        short_filename = os.path.basename(file_dict[file].filename)
        file_dict[file].save(os.path.join(orig_dir, short_filename))

    # Give the task to the celery worker
    result = celery_tasks.argmining_complete_pipeline.delay(temp_dir, cache=use_cache)

    # Return the celery task ID
    logger.info("** Started task %s **", str(result.id))
    logger.info("TASK STARTED (%s): %s"%(result.id, datetime.datetime.now().strftime("%y-%m-%d_%H:%M:%S")))
    return jsonify({'task_id': result.id})
    




@flask_app.route('/convert-to-dg', methods=['POST'])
def convertor():
    if request.method == 'POST':

        logger.info("Converting file!")

        f = request.files.get('file')
        if not f:
            return jsonify({"error": "No file uploaded"}), 400  # Handle missing file

        topic = request.form.get('topic')
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