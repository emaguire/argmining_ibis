from pydantic import BaseModel
from typing import List, Optional

class ibisComponent(BaseModel):
    id : str
    text : str
    orig : List[str]
    type : str
    parent: Optional[List[str]]
    pro: Optional[List[str]] = []
    con: Optional[List[str]] = []

class ibis(BaseModel):
    ibis: List[ibisComponent]