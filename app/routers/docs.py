from fastapi import APIRouter, Request, HTTPException
from fastapi.templating import Jinja2Templates
import markdown
import os
import aiofiles

router = APIRouter(
    prefix="/docs",
    tags=["docs"]
)

templates = Jinja2Templates(directory="app/templates")

DOCS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "docs")

def get_docs_list():
    docs = []
    if os.path.exists(DOCS_DIR):
        for filename in os.listdir(DOCS_DIR):
            if filename.endswith(".md"):
                name = filename[:-3]
                # Map filenames to titles (simple mapping)
                title = name.replace("_", " ").title()
                if name == "user_manual": title = "操作手册"
                elif name == "deployment": title = "部署文档"
                elif name == "design": title = "设计文档"
                elif name == "openapi": title = "API 文档"
                
                docs.append({"id": name, "title": title, "filename": filename})
    return docs

@router.get("/{doc_id}")
async def view_doc(request: Request, doc_id: str):
    if ".." in doc_id or "/" in doc_id or "\\" in doc_id:
        raise HTTPException(status_code=404, detail="Document not found")
    file_path = os.path.join(DOCS_DIR, f"{doc_id}.md")
    
    if not os.path.exists(file_path):
        # Try finding by checking list
        found = False
        for doc in get_docs_list():
             if doc["id"] == doc_id:
                 file_path = os.path.join(DOCS_DIR, doc["filename"])
                 found = True
                 break
        if not found:
            raise HTTPException(status_code=404, detail="Document not found")

    async with aiofiles.open(file_path, mode='r', encoding='utf-8') as f:
        content = await f.read()
        
    html_content = markdown.markdown(content, extensions=['fenced_code', 'tables'])
    
    return templates.TemplateResponse(request, "doc.html", {
        "content": html_content,
        "title": doc_id,
        "docs_list": get_docs_list(),
        "current_doc": doc_id
    })

@router.get("/")
async def docs_index(request: Request):
    docs = get_docs_list()
    if docs:
        return await view_doc(request, docs[0]["id"])
    return templates.TemplateResponse(request, "doc.html", {
        "content": "<h1>暂无文档</h1>",
        "title": "文档中心",
        "docs_list": [],
        "current_doc": ""
    })
