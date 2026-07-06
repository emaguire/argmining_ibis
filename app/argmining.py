import os
import sys
import datetime
import uuid
import tempfile
import shutil
from glob import glob
import json

import logging

import asyncio

from app import llm_caller
from app import intake_files
from app import text_to_ibis
from app import merge_ibis
from app import crosslink_ibis
from app import xaif_dg_convert



DEV_MODE = os.getenv('DEV_MODE', False)
CONCURRENCY=os.getenv('CONCURRENCY', 4)
CHUNK_SIZE=os.getenv('CHUNK_SIZE', 2000)

logger = logging.getLogger()
logger.setLevel(logging.INFO)
handler = logging.StreamHandler(sys.stdout)
handler.setLevel(logging.INFO)
formatter = logging.Formatter('[%(asctime)s][%(levelname)s]: %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)

async def argmine_ibis(temp_dir):
    chunk_size=CHUNK_SIZE
    logger.info("Chunk size: %s", str(chunk_size))
    semaphore = asyncio.Semaphore(CONCURRENCY)

    try:
        orig_dir = os.path.join(temp_dir, 'orig_files')
        text_dir = os.path.join(temp_dir, 'input_text')
        os.mkdir(text_dir)

        # Convert input files to plaintext
        local_input_files = glob(os.path.join(orig_dir, "*"))
        logger.info('Creating texts for %s', str(local_input_files))
        try:
            text_list = intake_files.create_texts(local_input_files, chunk_size=chunk_size, save_to_dir=text_dir)
        except Exception as e:
            return "Text-creation failed"
            # logger.error("Text-creation failed", exc_info=True)
            # logger.error("Text-creation failed", exc_info=True)
        
        # return "!!! FILE PROCESSING DONE"
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

        # return "!!! INITIAL ARGMINING ON CHUNKS DONE"
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

    return result_xaif


async def argmine_ibis_and_save(temp_dir):
    result_xaif = await argmine_ibis(temp_dir)
    
    try:
        with open(f"{temp_dir}/final.json", 'w') as f:
            json.dump(result_xaif, f, indent=4)
    except:
        with open(f"{temp_dir}/final.json", 'w') as f:
            json.dump({}, f, indent=4)
    
    return result_xaif