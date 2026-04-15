from pydantic import BaseModel, Field
from typing import List, Optional,Literal

# class ibisComponent(BaseModel):
#     id : str
#     text : str
#     orig : List[str]

# class ibisIssue(ibisComponent):
class ibisIssue(BaseModel):
    id : str
    text : str
    orig : List[str]
    type : Literal["issue"]
    parent: List[str]

class ibisPosition(BaseModel):
    id : str
    text : str
    orig : List[str]
    type : Literal["position"]
    parent: List[str]

class ibisArgument(BaseModel):
    id : str
    text : str
    orig : List[str]
    type : Literal["argument"]
    pro: List[str]
    con: List[str]



class ibis(BaseModel):
    ibis: List[ibisIssue | ibisPosition | ibisArgument]