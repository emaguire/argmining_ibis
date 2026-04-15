from flask import Flask, redirect, request, render_template, jsonify, render_template_string
# from . import application
import markdown2

import os
import sys
import subprocess
import time

import datetime
import json
from glob import glob

from app import llm_caller

from app import intake_files
from app import text_to_ibis
from app import merge_ibis
from app import crosslink_ibis

import logging

# Check dev mode for whether to do file cleanup
DEV_MODE = os.getenv('DEV_MODE', False)

# Add logs to the docker logs
logger = logging.getLogger()
logger.setLevel(logging.DEBUG)
handler = logging.StreamHandler(sys.stdout)
handler.setLevel(logging.DEBUG)
formatter = logging.Formatter('[%(asctime)s][%(levelname)s]: %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)

app = Flask(__name__)

# Useful functions

# !! Todo Add a mechanism for naming just in case there's an attempt to make multiple in the same second
def new_tmp_dir():
    temp_dir = f"temp_{datetime.datetime.now().strftime("%y-%m-%d_%H-%M")}_{llm_caller.MODEL_NAME.split('/')[0]}"
    os.mkdir(os.path.join('temp',temp_dir))
    temp_dir = os.path.join('temp',temp_dir)
    return temp_dir


# Checker entrypoints

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


@app.route('/sleepytime', methods=['GET'])
def sleepytime():
    sleep = request.args.get('sleep')
    if sleep is None:
        logger.info("Default sleep time of 20.")
        sleep=20
    else:
        sleep = float(sleep)
    logger.info("Going to sleep for %s seconds...", str(sleep))
    time.sleep(sleep)
    logger.info("Slept for %s seconds", str(sleep))
    return f"Successfully had a {sleep}-second sleep\n"


@app.route('/test', methods=['GET'])
def test_call():    
    if DEV_MODE:
        logger.info("Container running in dev mode.")
    else:
        logger.info("Container running in normal (non-dev) mode.")
    response = (llm_caller.test_llm())
    logger.info("Response type is %s", type(response))
    return jsonify(response)


@app.route('/testinstruct', methods=['GET'])
def test_instructor_call():
    if DEV_MODE:
        logger.info("Container running in dev mode.")
    else:
        logger.info("Container running in normal (non-dev) mode.")
    response = (llm_caller.test_instructor())
    logger.info("Response type is %s", type(response))
    return jsonify(response)

#############################################################
# Main entrypoint: intake original files and run end-to-end #
#############################################################


# Run the whole thing end-to-end
@app.route('/', methods=['POST'])
def argmine_ibis():
    if request.method == 'POST':

        #########################################################
        # 0. Make a temporary directory for intermediary files. #
        #########################################################
        temp_dir = new_tmp_dir()
        with open(f"{temp_dir}/MODEL_NAME.txt", 'w') as f:
            f.write(llm_caller.MODEL_NAME)

        #########################################
        # 1. Intake files and process to text #
        #########################################
        # !! Todo: add variable to allow user to adjust size of chunks

        # Check input
        # !! Todo: Change to using flagged list instead of individual flagged files?
        # f = request.files.getlist('file[]')
        file_list = request.files.getlist('file')
        if not file_list:
            return jsonify({"error": "No file uploaded"}), 400  # Handle missing file

        # Make copies of original input files
        # !! Todo: Handle multiple input file types
        orig_dir = os.path.join(temp_dir, 'orig_files')
        os.mkdir(orig_dir)
        
        for file in file_list:
            logger.info("Read file %s", file.filename)
            short_filename = os.path.basename(file.filename)
            file.save(os.path.join(orig_dir, short_filename))

        text_dir = os.path.join(temp_dir, 'input_text')
        os.mkdir(text_dir)

        # Convert input files to plaintext
        # !! Todo: make output chunk size adjustable
        local_input_files = glob(os.path.join(orig_dir, "*"))
        logger.info('Creating texts for %s', str(local_input_files))
        try:
            text_list = intake_files.create_texts(local_input_files, type='pdf', save_to_dir=text_dir)
        except Exception as e:
            logger.error("Text-creation failed", exc_info=True)
        

        ############################################
        # 2. Initial argmining on individual files #
        ############################################
        # For each created text chunk, create IBIS XAIF
        # Accumulate in a list of python dicts
        
        xaif_list = []
        for file_entry in text_list:
            if len(file_entry['text']) == 1: # only one chunk, no need to name output
                logger.info('Running text_to_ibis on %s', file_entry['origin'])
                try:
                    xaif_list += [text_to_ibis.text_to_ibis(file_entry['text'][0], origin_name=file_entry['origin'], save_to_dir=temp_dir)]
                except Exception as e:
                    logger.error('Failed to get initial text analysis for %s', file_entry['origin'], exc_info=True)
            elif len(file_entry['text']) > 1:
                counter = 0
                for chunk in file_entry['text']:
                    # chunk_name = f"{file_entry['origin']}_{counter}"
                    # chunk_name = f"{file_entry['origin'].rsplit('.',1)[0]}_{counter}"
                    namesplit = file_entry['origin'].rsplit('.',1)
                    if len(namesplit) > 1:
                        chunk_name = f"{namesplit[0]}_{counter}.{namesplit[-1]}"
                    else:
                        chunk_name = f"{namesplit[0]}_{counter}"

                    logger.info('Running text_to_ibis on content from %s (part %s)', chunk_name, str(counter))
                    try:
                        xaif_list += [text_to_ibis.text_to_ibis(chunk, origin_name=chunk_name, save_to_dir=temp_dir)]
                        logger.info("Completed for part %s", str(counter))
                    except Exception as e:
                        logger.error('Failed to get initial text analysis for %s', chunk_name, exc_info=True)
                    counter += 1
        

        #####################################
        # 3. Merge all resulting XAIF files #
        #####################################
        logging.info('Merging files into a single file')
        try:
            merged_xaif = merge_ibis.merge_xaif_list(xaif_list, save_to_dir=temp_dir)
        except Exception as e:
            logger.error("File merging failed", exc_info=True)


        ##################
        # 4. Merge nodes #
        ##################
        logging.info('Merging nodes')
        try:
            merged_xaif = merge_ibis.merge_ibis_nodes(merged_xaif, save_to_dir=temp_dir)
        except Exception as e:
            logger.error("Node merging failed", exc_info=True)


        #################
        # 5. Link nodes #
        ################# 
        logging.info('Linking nodes')
        try:
            result_xaif = crosslink_ibis.link_nodes(merged_xaif, save_to_dir=temp_dir)
        except Exception as e:
            result_xaif = merged_xaif
            logger.error("Node linking failed", exc_info=True)


        # Clean up the interim files
        # !! Todo: Clear temp at the end if this isn't in devmode
        if not DEV_MODE:
            logger.info("Cleaning up temp folder.")
            # os.remove(unique_filename)
            pass
        
        logger.info("Done!")

        return jsonify(result_xaif)
        # return f"Wow we saw {len(file_list)} file(s)! Copies of the files are saved in {local_input_files}"





# Todo: Any entrypoints which accept JSON should check whether the XAIF is valid IBIS XAIF at the first step

# Given text, run end-to-end from point of plaintext (skip pdf-processing, but still do chunking)
@app.route('/argmine-ibis', methods=['POST'])
def argmine_ibis_from_texts():
    #########################################################
    # 0. Make a temporary directory for intermediary files. #
    #########################################################
    # !! Todo Add a mechanism for naming just in case there's an attempt to make multiple in the same second
    temp_dir = new_tmp_dir()


    #########################################
    # 1. Intake files and process to text #
    #########################################
    # !! Todo: add variable to allow user to adjust size of chunks

    # Check input
    # !! Todo: Change to using flagged list instead of individual flagged files?
    # f = request.files.getlist('file[]')
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
            text_list = intake_files.create_texts(local_input_files, type='txt', save_to_dir=text_dir)
        except Exception as e:
            logger.error("Text-creation failed", exc_info=True)
    

    ############################################
    # 2. Initial argmining on individual files #
    ############################################
    # For each created text chunk, create IBIS XAIF
    # Accumulate in a list of python dicts
    
    xaif_list = []
    for file_entry in text_list:
        if len(file_entry['text']) == 1: # only one chunk, no need to name output
            logger.info('Running text_to_ibis on %s', file_entry['origin'])
            try:
                xaif_list += [text_to_ibis.text_to_ibis(file_entry['text'][0], origin_name=file_entry['origin'], save_to_dir=temp_dir)]
                time.sleep(30.0)
            except Exception as e:
                logger.error('Failed to get initial text analysis for %s', file_entry['origin'], exc_info=True)
        elif len(file_entry['text']) > 1:
            counter = 0
            for chunk in file_entry['text']:
                # chunk_name = f"{file_entry['origin']}_{counter}"
                # chunk_name = f"{file_entry['origin'].rsplit('.',1)[0]}_{counter}"
                namesplit = file_entry['origin'].rsplit('.',1)
                if len(namesplit) > 1:
                    chunk_name = f"{namesplit[0]}_{counter}.{namesplit[-1]}"
                else:
                    chunk_name = f"{namesplit[0]}_{counter}"

                logger.info('Running text_to_ibis on content from %s (part %s)', chunk_name, str(counter))
                try:
                    xaif_list += [text_to_ibis.text_to_ibis(chunk, origin_name=chunk_name, save_to_dir=temp_dir)]
                except Exception as e:
                    logger.error('Failed to get initial text analysis for %s', chunk_name, exc_info=True)
                counter += 1
    

    #####################################
    # 3. Merge all resulting XAIF files #
    #####################################
    logging.info('Merging files into a single file')
    try:
        merged_xaif = merge_ibis.merge_xaif_list(xaif_list, save_to_dir=temp_dir)
    except Exception as e:
        logger.error("File merging failed", exc_info=True)


    ##################
    # 4. Merge nodes #
    ##################
    logging.info('Merging nodes')
    try:
        merged_xaif = merge_ibis.merge_ibis_nodes(merged_xaif, save_to_dir=temp_dir)
    except Exception as e:
        logger.error("Node merging failed", exc_info=True)


    #################
    # 5. Link nodes #
    ################# 
    logging.info('Linking nodes')
    try:
        result_xaif = crosslink_ibis.link_nodes(merged_xaif, save_to_dir=temp_dir)
    except Exception as e:
        result_xaif = merged_xaif
        logger.error("Node linking failed", exc_info=True)


    # Clean up the interim files
    # !! Todo: Clear temp at the end if this isn't in devmode
    if not DEV_MODE:
        logger.info("Cleaning up temp folder.")
        # os.remove(unique_filename)
        pass
    
    logger.info("Done!")

    return jsonify(result_xaif)


# Given a list of XAIF json file names, merge into one JSON and return, without any matching or merging
@app.route('/merge-files-only', methods=['POST'])
def app_minimal_merge_ibis():
    if request.method == 'POST':
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

        # U R HERE. Put all the file content in a list of dicts called xaif_list
        xaif_list = []
         
        
        logging.info('Merging files into a single file')
        try:
            merged_xaif = merge_ibis.merge_xaif_list(xaif_list, save_to_dir=temp_dir)
        except Exception as e:
            logger.error("File merging failed", exc_info=True)
        return jsonify(result_xaif)  # Return as JSON response

# Given an IBIS-compliant XAIF json file name, attempts node merging 
@app.route('/argmine-ibis-merge', methods=['GET', 'POST'])
def app_merge_ibis():
    if request.method == 'POST':
        f = request.files.get('file')
        if not f:
            return jsonify({"error": "No file uploaded"}), 400  # Handle missing file

        # Generate a unique filename
        unique_filename = f"{uuid.uuid4()}.json"
        f.save(unique_filename)

        try:
            with open(unique_filename, 'r') as ff:
                content = json.load(ff)  # Validate JSON format
        except json.JSONDecodeError:
            os.remove(unique_filename)
            return jsonify({"error": "Invalid JSON format"}), 400
        
        ####################################
        #
        #   Call the code for the specific 
        #   AMF module here...
        #
        #####################################

        result_xaif = content  # Replace this with the actual processed data

        # Cleanup the uploaded file
        os.remove(unique_filename)

        return jsonify(result_xaif)  # Return as JSON response

# Given an XAIF IBIS json file name, add links between nodes and return
@app.route('/argmine-ibis-link', methods=['GET', 'POST'])
def app_link_ibis():
    if request.method == 'POST':
        f = request.files.get('file')
        if not f:
            return jsonify({"error": "No file uploaded"}), 400  # Handle missing file

        # Generate a unique filename
        unique_filename = f"{uuid.uuid4()}.json"
        f.save(unique_filename)

        try:
            with open(unique_filename, 'r') as ff:
                content = json.load(ff)  # Validate JSON format
        except json.JSONDecodeError:
            os.remove(unique_filename)
            return jsonify({"error": "Invalid JSON format"}), 400
        
        ####################################
        #
        #   Call the code for the specific 
        #   AMF module here...
        #
        #####################################

        result_xaif = content  # Replace this with the actual processed data

        # Cleanup the uploaded file
        os.remove(unique_filename)

        return jsonify(result_xaif)  # Return as JSON response

    elif request.method == 'GET':
        # Get the absolute path to README.md in the root directory
        readme_path = os.path.join(os.path.abspath(os.path.dirname(__file__)), '..', 'README.md')
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
