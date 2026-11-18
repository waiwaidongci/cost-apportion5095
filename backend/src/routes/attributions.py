from fastapi import APIRouter,Depends,HTTPException
from src.config.database import database
from src.controllers.auth import current,editor
from src.models.run import Attribution
from src.schemas.requests import AttributionInput
from src.services.attribution import attribute
from src.utils.serialize import row
router=APIRouter()
@router.get('/attributions')
def attributions(db=Depends(database),u=Depends(current)): return [row(x) for x in db.query(Attribution).order_by(Attribution.id.desc()).all()]
@router.post('/attributions')
def create(b:AttributionInput,db=Depends(database),u=Depends(editor)): return row(attribute(db,u,b.base_run,b.compare_run))
@router.get('/attributions/{id}')
def detail(id:int,db=Depends(database),u=Depends(current)):
 obj=db.get(Attribution,id)
 if not obj: raise HTTPException(404,'归因结果不存在')
 return row(obj)
