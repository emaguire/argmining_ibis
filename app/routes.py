from flask import Flask, redirect, request, render_template, jsonify, render_template_string
from . import application
import markdown2
# import uuid

import os
import sys
import subprocess

import datetime
import json
from glob import glob

from app import intake_files
# from app import text_to_ibis
# from app import merge_ibis
# from app import crosslink_ibis


import logging

# Add logs to the docker logs
logger = logging.getLogger()
logger.setLevel(logging.DEBUG)

handler = logging.StreamHandler(sys.stdout)
handler.setLevel(logging.DEBUG)

formatter = logging.Formatter('[%(asctime)s][%(levelname)s]: %(message)s')
# formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

handler.setFormatter(formatter)
logger.addHandler(handler)



app = Flask(__name__)

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


# Run the whole thing end-to-end
@app.route('/', methods=['POST'])
def argmine_ibis():
    if request.method == 'POST':
        # f = request.files.getlist('file[]')
        # Check for input first
        file_list = request.files.getlist('file')
        if not file_list:
            return jsonify({"error": "No file uploaded"}), 400  # Handle missing file

        # Make a temporary directory for intermediary files.
        # !! Add a mechanism for naming just in case there's an attempt to make multiple in the same second
        # !! Add a mechanism to clear temp at the end if this isn't in devmode (add an env var in dev compose that can be checked)
        temp_dir = f"temp_{datetime.datetime.now().strftime("%y%m%d%m%H%M%S")}"
        os.mkdir(os.path.join('temp',temp_dir))
        temp_dir = os.path.join('temp',temp_dir)

        # Used this earlier to double check reqs from inside the container.
        reqs = subprocess.run([sys.executable, '-m', 'pip', 'freeze'], check=True, capture_output=True, text=True).stdout
        with open(os.path.join(temp_dir, "container_reqs_combined.txt"), 'w') as f:
            f.write(str(reqs))
        # return 'hello'

        # Save a copy of original input files
        # This process can be made nicer for multiple input file types later.
        # It'll do for now
        orig_dir = os.path.join(temp_dir, 'orig_files')
        os.mkdir(orig_dir)
        
        for file in file_list:
            logger.info("Read file %s", file.filename)
            short_filename = os.path.basename(file.filename)
            file.save(os.path.join(orig_dir, short_filename))

        text_dir = os.path.join(temp_dir, 'input_text')
        os.mkdir(text_dir)



        local_input_files = glob(os.path.join(orig_dir, "*"))

        logger.info('Creating texts for %s', str(local_input_files))
        try:
            text_list = intake_files.create_texts(local_input_files, save_to_dir=text_dir)
        except Exception as e:
            logger.error("Text-creation failed", exc_info=True)
        

        # with open(f"temp/check_{datetime.datetime.now().strftime("%y%m%d%m%H%M%S")}", 'w') as f:
        #     f.write("hello")

        # # Generate a unique filename
        # unique_filename = f"{uuid.uuid4()}.json"
        # f.save(unique_filename)

        
        ####################################
        #
        #   Call the code for the specific 
        #   AMF module here...
        #
        #####################################

        # result_xaif = content  # Replace this with the actual processed data

        # Cleanup the uploaded file
        # os.remove(unique_filename)
        # return jsonify(result_xaif)
        return f"Wow we saw {len(file_list)} file(s)! Copies of the files are saved in {local_input_files}"

# Given a list of XAIF json file names, merge into one JSON and return, without any matching or merging
@app.route('/argmine-merge-only', methods=['GET', 'POST'])
def minimal_merge_ibis():
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

# Given a list of XAIF json file names, merge into one JSON and return, including node merging
@app.route('/argmine-merge', methods=['GET', 'POST'])
def merge_ibis():
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

# Given an XAIF json file, add links 
@app.route('/argmine-link', methods=['GET', 'POST'])
def link_ibis():
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
