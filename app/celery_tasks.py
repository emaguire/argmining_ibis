from celery import Celery
from asgiref.sync import async_to_sync

from app import argmining
from app.llm_caller import hello_world
import asyncio

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
def argmining_complete_pipeline(dir_name):
    result = async_to_sync(argmining.argmine_ibis)(dir_name)
    return result

@celery_app.task
def dummy_map():
    return {'name': 'barbara'}

@celery_app.task
def hello_world_llm():
    hello_response = hello_world()
    return hello_response