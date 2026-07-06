from celery import Celery
from asgiref.sync import async_to_sync

from glob import glob
import shutil
import os
import json
import hashlib

from app import argmining
from app.llm_caller import hello_world
import asyncio

import sys
import logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)
handler = logging.StreamHandler(sys.stdout)
handler.setLevel(logging.INFO)
formatter = logging.Formatter('[%(asctime)s][%(levelname)s]: %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)



DEV_MODE = os.getenv('DEV_MODE', False)


celery_app = Celery('celery_tasks', backend='redis://localhost', broker='pyamqp://')

async def async_waiting():
    await asyncio.sleep(20)
    return "I have waited for 20 seconds"

async def async_with_arg(x):
    await asyncio.sleep(1)
    return f"I was passed '{x}'\n"

################
# CELERY TASKS #
################

# Test functions
@celery_app.task
def add(x, y):
    return x + y

@celery_app.task
def twenty_secs():
    result = async_to_sync(async_waiting)()
    return result

@celery_app.task
def pass_an_arg(x):
    result = async_to_sync(async_with_arg)(x)
    return result

@celery_app.task
def argmining_complete_pipeline(dir_name, cache=False):
    # If cache has been set and only one file is submitted
    # return the existing result for that file
    # (Deal with using multiple cached files per request later)
    if cache:
        # Check if cache has been set to somewhere else
        cache_dir = os.getenv('ARGMINE_CACHE', 'cache')

        input_file_list = glob(f"{dir_name}/orig_files/*")
        if len(input_file_list) == 1:
            with open(input_file_list[0], 'rb') as f:
                filehex = hashlib.file_digest(f, "blake2b").hexdigest()
            
        # Check if a result exists for this file: 
        # clean up and return it if so
        cache_match = glob(f"{cache_dir}/{filehex}.json")
        if len(cache_match) == 1:
            logger.info("Found a cached result for the submitted document")
            logger.info("Loading %s", str(cache_match[0]))
            with open(cache_match[0]) as f:
                result = json.loads(f.read())
            if not DEV_MODE:
                shutil.rmtree(dir_name)
            return result

    result = async_to_sync(argmining.argmine_ibis)(dir_name)

    # If cache has been set and only one file is submitted
    # save the result for that file for potential future use
    if cache and len(input_file_list) == 1:
        with open(f"{cache_dir}/{filehex}.json", 'w') as f:
            json.dump(result, f, indent=4)

    return result

@celery_app.task
def dummy_json():
    return {'name': 'barbara'}

@celery_app.task
def hello_world_llm():
    hello_response = hello_world()
    return hello_response