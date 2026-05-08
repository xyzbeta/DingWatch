from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from typing import List
from .. import models, schemas, database, crud

router = APIRouter(
    prefix="/api/v1",
    tags=["config"]
)

# User API
@router.post("/users", response_model=schemas.UserWithTeams)
def create_user(user: schemas.UserCreate, db: Session = Depends(database.get_db)):
    db_user = db.query(models.User).filter(models.User.phone_number == user.phone_number).first()
    if db_user:
        raise HTTPException(status_code=400, detail="Phone number already registered")
    return crud.create_user(db=db, user=user)

@router.post("/users/batch")
def batch_create_users(content: str = Body(..., embed=True), db: Session = Depends(database.get_db)):
    """
    Batch create users from CSV-like string.
    Format: name,phone_number (one per line)
    """
    lines = content.strip().split('\n')
    success_count = 0
    errors = []
    
    for line in lines:
        line = line.strip()
        if not line: continue
        parts = [p.strip() for p in line.split(',')]
        if len(parts) < 2:
            errors.append(f"Invalid format: {line}")
            continue
            
        name, phone = parts[0], parts[1]
        
        # Check existence
        if db.query(models.User).filter(models.User.phone_number == phone).first():
            errors.append(f"Phone exists: {phone}")
            continue
            
        try:
            crud.create_user(db, schemas.UserCreate(name=name, phone_number=phone))
            success_count += 1
        except Exception as e:
            errors.append(f"Error adding {name}: {str(e)}")
            
    return {"success": success_count, "errors": errors}

@router.put("/users/{user_id}", response_model=schemas.UserWithTeams)
def update_user(user_id: int, user: schemas.UserCreate, db: Session = Depends(database.get_db)):
    # Check if phone number is used by ANOTHER user
    existing_user = db.query(models.User).filter(
        models.User.phone_number == user.phone_number,
        models.User.id != user_id
    ).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Phone number already registered by another user")
        
    db_user = crud.update_user(db, user_id, user)
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")
    return db_user

@router.get("/users", response_model=List[schemas.UserWithTeams])
def read_users(skip: int = 0, limit: int = 100, db: Session = Depends(database.get_db)):
    return crud.get_users(db, skip=skip, limit=limit)

@router.delete("/users/{user_id}")
def delete_user(user_id: int, db: Session = Depends(database.get_db)):
    db_user = db.query(models.User).filter(models.User.id == user_id).first()
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")
    db.delete(db_user)
    db.commit()
    return {"ok": True}

# Team API
@router.post("/teams", response_model=schemas.Team)
def create_team(team: schemas.TeamCreate, db: Session = Depends(database.get_db)):
    return crud.create_team(db=db, team=team)

@router.post("/teams/batch")
def batch_create_teams(content: str = Body(..., embed=True), db: Session = Depends(database.get_db)):
    """
    Batch create teams from CSV-like string.
    Format: name,description (one per line)
    """
    lines = content.strip().split('\n')
    success_count = 0
    errors = []
    
    for line in lines:
        line = line.strip()
        if not line: continue
        parts = [p.strip() for p in line.split(',')]
        name = parts[0]
        description = parts[1] if len(parts) > 1 else None
        
        # Check existence
        if db.query(models.Team).filter(models.Team.name == name).first():
            errors.append(f"Team exists: {name}")
            continue
            
        try:
            crud.create_team(db, schemas.TeamCreate(name=name, description=description))
            success_count += 1
        except Exception as e:
            errors.append(f"Error adding {name}: {str(e)}")
            
    return {"success": success_count, "errors": errors}

@router.put("/teams/{team_id}", response_model=schemas.Team)
def update_team(team_id: int, team: schemas.TeamCreate, db: Session = Depends(database.get_db)):
    db_team = crud.update_team(db, team_id, team)
    if not db_team:
        raise HTTPException(status_code=404, detail="Team not found")
    return db_team

@router.get("/teams", response_model=List[schemas.Team])
def read_teams(skip: int = 0, limit: int = 100, db: Session = Depends(database.get_db)):
    return crud.get_teams(db, skip=skip, limit=limit)

@router.delete("/teams/{team_id}")
def delete_team(team_id: int, db: Session = Depends(database.get_db)):
    success = crud.delete_team(db, team_id)
    if not success:
        raise HTTPException(status_code=404, detail="Team not found")
    return {"ok": True}

# Rule API
@router.post("/rules", response_model=schemas.Rule)
def create_rule(rule: schemas.RuleCreate, db: Session = Depends(database.get_db)):
    db_rule = db.query(models.Rule).filter(models.Rule.name == rule.name).first()
    if db_rule:
        raise HTTPException(status_code=400, detail="Rule name already exists")
    return crud.create_rule(db=db, rule=rule)

@router.put("/rules/{rule_id}", response_model=schemas.Rule)
def update_rule(rule_id: int, rule: schemas.RuleCreate, db: Session = Depends(database.get_db)):
    db_rule = crud.update_rule(db, rule_id, rule)
    if not db_rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    return db_rule

@router.get("/rules", response_model=List[schemas.Rule])
def read_rules(skip: int = 0, limit: int = 100, tag: str = None, db: Session = Depends(database.get_db)):
    return crud.get_rules(db, skip=skip, limit=limit, tag=tag)

@router.get("/tags", response_model=List[schemas.Tag])
def read_tags(db: Session = Depends(database.get_db)):
    return crud.get_tags(db)

@router.delete("/rules/{rule_id}")
def delete_rule(rule_id: int, db: Session = Depends(database.get_db)):
    db_rule = db.query(models.Rule).filter(models.Rule.id == rule_id).first()
    if not db_rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    db.delete(db_rule)
    db.commit()
    return {"ok": True}
