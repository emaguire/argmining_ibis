# This is not a main file for a final implementation!
# It's just to test that all the functions work and pass between each other as expected.

import intake_files
import text_to_ibis
import merge_ibis
import crosslink_ibis

import datetime
import os
import sys
import json

# Handling arguments like this isn't relevant to API usage, but need it for easy commandline testing
import logging
import argparse

# Create parser for accepting list of files
parser = argparse.ArgumentParser()
parser.add_argument('-f','--file-list', nargs='+', default=[])
parser.add_argument('-d', '--debug', default=False)

# Create logger
logger = logging.getLogger()
logging.basicConfig(format='%(asctime)s %(message)s')


if __name__ == '__main__':
    # 0. Create a temp dir so that interim outputs can be examined later
    temp_dir = f"temp_{datetime.datetime.now().strftime("%y%m%d%m%H%M%S")}"
    os.mkdir(os.path.join('..','temp',temp_dir))
    temp_dir = os.path.join('..','temp',temp_dir)
    
    args = parser.parse_args()
    logging.basicConfig(filename=os.path.join(temp_dir, 'run.log'), encoding='utf-8', level=logging.DEBUG)

    # 1. Create texts from input files
    orig_files = args.file_list
    logger.info('Creating texts for %s', str(orig_files))
    try:
        text_list = intake_files.create_texts(orig_files, save_to_dir=temp_dir)
    except Exception as e:
        logger.error("Text-creation failed", exc_info=True)

    # 2. For each created text from the argument list, read string and create IBIS XAIF
    # !! Consider adding faux extension to chunk name fake filenames
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
                chunk_name = f"{file_entry['origin']}_{counter}"
                logger.info('Running text_to_ibis on %s', chunk_name)
                try:
                    xaif_list += [text_to_ibis.text_to_ibis(chunk, origin_name=chunk_name, save_to_dir=temp_dir)]
                except Exception as e:
                    logger.error('Failed to get initial text analysis for %s', chunk_name, exc_info=True)
                counter += 1

    # 3. Merge these files into a single xaif
    logging.info('Merging files into a single file')
    try:
        merged_xaif = merge_ibis.merge_xaif_list(xaif_list, save_to_dir=temp_dir)
    except Exception as e:
        logger.error("File merging failed", exc_info=True)

    # 4. Merge nodes where appropriate
    logging.info('Merging nodes')
    try:
        merged_xaif = merge_ibis.merge_ibis_nodes(merged_xaif, save_to_dir=temp_dir)
    except Exception as e:
        logger.error("Node merging failed", exc_info=True)

    # 5. Link nodes where appropriate
    logging.info('Linking nodes')
    try:
        merged_xaif = crosslink_ibis.link_nodes(merged_xaif, save_to_dir=temp_dir)
    except Exception as e:
        logger.error("Node linking failed", exc_info=True)

    logging.info('Done!')
    # Return? print? Somehow serve content of final version
    # Cross-linking is the last step: that's the final one, no need to resave.
    print(merged_xaif)


    