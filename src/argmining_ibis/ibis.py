from pydantic import BaseModel, Field
from typing import List, Optional,Literal



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
    ibis: List[ibisIssue | ibisPosition | ibisArgument] = []



class ibisOrigin(BaseModel):
    quote: str
    src: str

class ibisIssueSourced(ibisIssue):
    orig : List[ibisOrigin]

class ibisPositionSourced(ibisPosition):
    orig : List[ibisOrigin]


class ibisArgumentSourced(ibisArgument):
    orig : List[ibisOrigin]

class ibisSourced(BaseModel):
    ibis: List[ibisIssueSourced | ibisPositionSourced | ibisArgumentSourced] = []
