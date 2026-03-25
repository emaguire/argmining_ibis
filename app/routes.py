from flask import redirect, request, render_template, jsonify, render_template_string
from . import application
import json
import os
import uuid
import markdown2

@application.route('/', methods=['GET'])
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
@application.route('/', methods=['POST'])
def argmine_ibis():
    if request.method == 'POST':
        f = request.files.get('file')
        if not f:
            return jsonify({"error": "No file uploaded"}), 400  # Handle missing file

        # Generate a unique filename
        unique_filename = f"{uuid.uuid4()}.json"
        f.save(unique_filename)

        
        ####################################
        #
        #   Call the code for the specific 
        #   AMF module here...
        #
        #####################################

        # result_xaif = content  # Replace this with the actual processed data

        # Cleanup the uploaded file
        # os.remove(unique_filename)
        return "Wow we saw some files!"

# Given a list of XAIF json file names, merge into one JSON and return, without any matching or merging
@application.route('/argmine-merge-only', methods=['GET', 'POST'])
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
@application.route('/argmine-merge', methods=['GET', 'POST'])
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
@application.route('/argmine-link', methods=['GET', 'POST'])
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
