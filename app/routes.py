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

from app import llm_caller

from app import intake_files
from app import text_to_ibis
from app import merge_ibis
from app import crosslink_ibis
from app import utils

import asyncio
import logging

# Check dev mode for whether to do file cleanup
DEV_MODE = os.getenv('DEV_MODE', False)
CONCURRENCY = 2

# Add logs to the docker logs
logger = logging.getLogger()
logger.setLevel(logging.INFO)
handler = logging.StreamHandler(sys.stdout)
handler.setLevel(logging.INFO)
formatter = logging.Formatter('[%(asctime)s][%(levelname)s]: %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)

app = Flask(__name__)

# Useful functions

# !! Todo Add a mechanism for naming just in case there's an attempt to make multiple in the same second
def new_tmp_dir():
    if DEV_MODE:
        temp_dir = f"temp_{datetime.datetime.now().strftime("%y-%m-%d_%H-%M")}_{llm_caller.MODEL_NAME.split('/')[0]}"
    else:
        temp_dir = os.path.join(tempfile.gettempdir(), str(uuid.uuid4()))
    
    os.mkdir(os.path.join('temp',temp_dir))
    temp_dir = os.path.join('temp',temp_dir)
    return temp_dir


# Testing/dev entrypoints

# Check the llm response is working
@app.route('/test', methods=['GET'])
def test_call():    
    if DEV_MODE:
        logger.info("Container running in dev mode.")
    else:
        logger.info("Container running in normal (non-dev) mode.")
    response = llm_caller.test_llm()
    logger.info("Response type is %s", type(response))
    return jsonify(response)

# Sanity-checking test for async
@app.route('/async', methods=['GET'])
async def test_async():    
    if DEV_MODE:
        logger.info("Container running in dev mode.")
    else:
        logger.info("Container running in normal (non-dev) mode.")
    
    results = []
    for i in range(0,3):
        result = await llm_caller.test_llm_split(dog_select=i)
        results.append(result)

    semaphore = asyncio.Semaphore(CONCURRENCY)

    async def fetch_dog(dog_select):
        async with semaphore:
            return await llm_caller.test_llm_split(dog_select=dog_select)

    nums = list(range(0,6))
    tasks = [fetch_dog(i) for i in nums]
    results = await asyncio.gather(*tasks)

    logger.info("Response type is %s", type(results))
    return str(results)



# Tester for possible use of Instructor
@app.route('/testinstruct', methods=['GET'])
def test_instructor_call():
    if DEV_MODE:
        logger.info("Container running in dev mode.")
    else:
        logger.info("Container running in normal (non-dev) mode.")
    response = (llm_caller.test_instructor())
    logger.info("Response type is %s", type(response))
    return jsonify(response)


# An endpoint for ad hoc tests
@app.route('/scratch', methods=['GET'])
async def scratch_tester():
    input_path = "./temp/temp_26-05-10_16-41_nvidia/xaifmerge_26051005164613.json"
    with open(input_path) as f:
        ibis_xaif = json.loads(f.read())

    ibis_xaif = await merge_ibis.graft_issues(ibis_xaif)

    return jsonify(ibis_xaif)


###################
# Docs entrypoint #
###################

@app.route('/', methods=['GET'])
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


#############################################################
# Main entrypoint: intake original files and run end-to-end #
#############################################################


# Run the whole thing end-to-end
@app.route('/', methods=['POST'])
async def argmine_ibis():
    chunk_size=4000
    logger.info("Chunk size: %s", str(chunk_size))

    semaphore = asyncio.Semaphore(CONCURRENCY)

    #########################################################
    # 0. Make a temporary directory for intermediary files. #
    #########################################################
    temp_dir = new_tmp_dir()
    if DEV_MODE:
        with open(f"{temp_dir}/MODEL_NAME.txt", 'w') as f:
            f.write(llm_caller.MODEL_NAME)
    
    try:
        #######################################
        # 1. Intake files and process to text #
        #######################################

        # Check input
        file_list = request.files.getlist('file')
        if not file_list:
            return jsonify({"error": "No file uploaded"}), 400  # Handle missing file

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





# Todo: Any entrypoints which accept JSON should check whether the XAIF is valid IBIS XAIF at the first step

# Given text, run end-to-end from point of plaintext (skip pdf-processing, but still do chunking)
@app.route('/argmine-ibis', methods=['POST'])
async def argmine_ibis_from_texts():
    chunk_size=4000
    logger.info("Chunk size: %s", str(chunk_size))

    semaphore = asyncio.Semaphore(CONCURRENCY)
    #########################################################
    # 0. Make a temporary directory for intermediary files. #
    #########################################################
    temp_dir = new_tmp_dir()
    if DEV_MODE:
        with open(f"{temp_dir}/MODEL_NAME.txt", 'w') as f:
            f.write(llm_caller.MODEL_NAME)

    try:
        #########################################
        # 1. Intake files and process to text #
        #########################################
        # !! Todo: add variable to allow user to adjust size of chunks

        # Check input
        file_list = request.files.getlist('file')
        if not file_list:
            return jsonify({"error": "No file uploaded"}), 400  # Handle missing file

        # Make copies of original input files
        orig_dir = os.path.join(temp_dir, 'orig_files')
        os.mkdir(orig_dir)
        
        for file in file_list:
            logger.info("Read file %s", file.filename)
            short_filename = os.path.basename(file.filename)
            file.save(os.path.join(orig_dir, short_filename))

        text_dir = os.path.join(temp_dir, 'input_text')
        os.mkdir(text_dir)

        # Chunk text files
        local_input_files = glob(os.path.join(orig_dir, "*"))
        text_list = []
        for input_file in local_input_files:
            logger.info('Chunking text for %s', str(input_file))
            try:
                text_list = intake_files.create_texts(local_input_files, chunk_size=chunk_size, save_to_dir=text_dir)
            except Exception as e:
                logger.error("Text-creation failed", exc_info=True)
        

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


    # Clean up the interim files
    finally:
        if not DEV_MODE:
            logger.info("Cleaning up temp directory.")
            shutil.rmtree(temp_dir)
    
    logger.info("Done!")

    return jsonify(result_xaif)


# Given a list of XAIF json file names, merge into one JSON and return, without any matching or merging
@app.route('/merge-files-only', methods=['POST'])
def app_minimal_merge_ibis():
    file_list = request.files.getlist('file')
    if not file_list:
        return jsonify({"error": "No file uploaded"}), 400  # Handle missing file

    temp_dir = new_tmp_dir()

    # Make copies of original input files
    orig_dir = os.path.join(temp_dir, 'orig_files')
    os.mkdir(orig_dir)

    for file in file_list:
        logger.info("Read file %s", file.filename)
        short_filename = os.path.basename(file.filename)
        try:
            file.save(os.path.join(orig_dir, short_filename))
        except:
            return jsonify({"error": "Invalid JSON format"}), 400

    # Load list 
    xaif_list = []
    orig_file_list = glob(f"{orig_dir}/*")
    for orig in orig_file_list:
        with open(orig) as f:
            try:
                xaif_list += [json.loads(f.read())]
            except Exception as e:
                logging.error("Couldn't load file %s", os.path.basename(orig))

    logging.info('Merging files into a single file')
    try:
        merged_xaif = merge_ibis.merge_xaif_list(xaif_list, save_to_dir=temp_dir)
    except Exception as e:
        logger.error("File merging failed", exc_info=True)
        merged_xaif = {'error': 'Merging failed'}

    # Clean up the interim files
    finally:
        if not DEV_MODE:
            logger.info("Cleaning up temp directory.")
            shutil.rmtree(temp_dir)

    return jsonify(merged_xaif)  # Return as JSON response


# Given an IBIS-compliant XAIF json file name, attempts node merging 
@app.route('/argmine-ibis-merge', methods=['POST'])
async def app_merge_ibis():
    #########################################################
    # 0. Make a temporary directory for intermediary files. #
    #########################################################
    temp_dir = new_tmp_dir()
    if DEV_MODE:
        with open(f"{temp_dir}/MODEL_NAME.txt", 'w') as f:
            f.write(llm_caller.MODEL_NAME)
    
    try:
        ##################
        # 1. Intake file #
        ##################
        file = request.files.getlist('file')
        
        # Make copies of original input file
        orig_dir = os.path.join(temp_dir, 'orig_files')
        os.mkdir(orig_dir)

        logger.info("Read file %s", file.filename)
        short_filename = os.path.basename(file.filename)
        try:
            file.save(os.path.join(orig_dir, short_filename))
        except:
            return jsonify({"error": "Invalid JSON format"}), 400

        # Load
        with open(os.path.join(orig_dir, short_filename)) as f:
            try:
                xaif = json.loads(f.read())
            except Exception as e:
                logging.error("Couldn't load file %s", short_filename)
                return jsonify({'error': f"couldn't load {short_filename}"})
        
        ###############
        # Merge nodes #
        ###############
        try:
            merged_xaif = await merge_ibis.merge_ibis_nodes(merged_xaif, save_to_dir=temp_dir)
        except Exception as e:
            logger.error("Node merging failed", exc_info=True)
            merged_xaif = xaif

    finally:
        if not DEV_MODE:
            logger.info("Cleaning up temp directory.")
            shutil.rmtree(temp_dir)

    return jsonify(merged_xaif)  # Return as JSON response



# Given an XAIF IBIS json file name, add links between nodes and return
@app.route('/argmine-ibis-link', methods=['POST'])
async def app_link_ibis():
            #########################################################
    # 0. Make a temporary directory for intermediary files. #
    #########################################################
    temp_dir = new_tmp_dir()
    if DEV_MODE:
        with open(f"{temp_dir}/MODEL_NAME.txt", 'w') as f:
            f.write(llm_caller.MODEL_NAME)
    
    try:
        ##################
        # 1. Intake file #
        ##################
        file = request.files.getlist('file')
        
        # Make copies of original input file
        orig_dir = os.path.join(temp_dir, 'orig_files')
        os.mkdir(orig_dir)

        logger.info("Read file %s", file.filename)
        short_filename = os.path.basename(file.filename)
        try:
            file.save(os.path.join(orig_dir, short_filename))
        except:
            return jsonify({"error": "Invalid JSON format"}), 400

        # Load
        with open(os.path.join(orig_dir, short_filename)) as f:
            try:
                xaif = json.loads(f.read())
            except Exception as e:
                logging.error("Couldn't load file %s", short_filename)
                return jsonify({'error': f"couldn't load {short_filename}"})
        
        ###############
        # Link nodes #
        ###############
        try:
            result_xaif = await crosslink_ibis.link_nodes(xaif, save_to_dir=temp_dir)
        except Exception as e:
            result_xaif = xaif
            logger.error("Node linking failed", exc_info=True)

    finally:
        if not DEV_MODE:
            logger.info("Cleaning up temp directory.")
            shutil.rmtree(temp_dir)

    return jsonify(result_xaif)  # Return as JSON response