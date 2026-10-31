from __future__ import annotations

import hashlib
import io
import json
import logging
import mimetypes
import re
import secrets
import sqlite3
import uuid
import zipfile
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional

import qrcode
from fastapi import Body, Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image

from .db import BACKUPS, COMMUNITY, DB, EXPORTS, LOGS, ROOT, STORAGE, audit, connect, get_one, init_db, must_exist, now, password_hash, rows, verify_password
from .exporter import get_data, make_export
from .drafts import draft_detail, draft_metadata, initial_blocks, make_draft_export, source_attachments, source_status
from .backup import create_backup
from .archive_excel import workbook_bytes, read_records
from .network import addresses, validate_base

init_db()
logging.basicConfig(filename=LOGS / "system.log", level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s", encoding="utf-8")
app = FastAPI(title=COMMUNITY + "电梯管理台账", docs_url=None, redoc_url=None)
TYPES = {"日常维保", "故障", "维修", "配件更换", "检验/检查", "资料补充", "其他"}
STATUSES = {"正常", "故障", "维修中", "停梯", "待处理"}
CATEGORIES = {"工作现场照片", "维修记录", "维保记录", "报价单", "业主签字单", "检测报告", "验收资料", "其他"}
EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".pdf", ".doc", ".docx", ".xls", ".xlsx"}
MAX_UPLOAD = 20 * 1024 * 1024


@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    return JSONResponse({"detail": "输入格式不正确，请检查日期、数字和必填项目"}, status_code=400)


def error(message, status=400):
    raise HTTPException(status_code=status, detail=message)


def require_text(value, label, limit=200):
    if value is not None and not isinstance(value, str):
        error("文字内容格式不正确")
    value = (value or "").strip()
    if any((ord(c) < 32 and c not in "\t\n\r") or 0xD800 <= ord(c) <= 0xDFFF or ord(c) in (0xFFFE, 0xFFFF) for c in value):
        error("文字内容含有无法保存的控制字符，请重新输入")
    if not value or len(value) > limit:
        error(f"{label}不能为空，且不能超过{limit}字")
    return value


def optional_text(value, limit=2000):
    if value is not None and not isinstance(value, str):
        error("文字内容格式不正确")
    value = (value or "").strip()
    if any((ord(c) < 32 and c not in "\t\n\r") or 0xD800 <= ord(c) <= 0xDFFF or ord(c) in (0xFFFE, 0xFFFF) for c in value):
        error("文字内容含有无法保存的控制字符，请重新输入")
    if len(value) > limit:
        error(f"内容不能超过{limit}字")
    return value


def day(value, label="日期", required=False):
    if not value:
        if required:
            error(f"{label}不能为空")
        return None
    try:
        return date.fromisoformat(str(value)).isoformat()
    except ValueError:
        error(f"{label}格式不正确")


def money(value):
    try:
        amount = Decimal(str(value if value is not None else "0"))
        if not amount.is_finite() or amount < 0 or amount > 100_000_000 or amount.as_tuple().exponent < -2:
            raise ValueError
        return int(amount * 100)
    except (InvalidOperation, ValueError):
        error("金额请输入不小于0、最多两位小数的数字")


def positive_int(value, label, minimum=0):
    if isinstance(value, bool):
        error(f"{label}必须是整数")
    try:
        number = int(value)
        if str(number) != str(value).strip() or number < minimum or number > 100000:
            raise ValueError
        return number
    except (ValueError, TypeError):
        error(f"{label}必须是不小于{minimum}的整数")


def flag(value, label):
    if type(value) not in (bool, int) or value not in (0, 1):
        error(f"{label}请选择是或否")
    return int(value)


def actor(request: Request):
    token = request.cookies.get("elevator_session")
    if not token:
        error("请先登录", 401)
    digest = hashlib.sha256(token.encode()).hexdigest()
    with connect() as db:
        user = get_one(db, """SELECT u.id,u.username,u.display_name,u.role FROM sessions s
          JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires_at>? AND u.active=1""", (digest, now()))
    if not user:
        error("登录已过期，请重新登录", 401)
    return user


def admin(user=Depends(actor)):
    if user["role"] != "admin":
        error("只有管理员可以进行此操作", 403)
    return user


@app.middleware("http")
async def guard(request: Request, call_next):
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        origin = request.headers.get("origin")
        if origin and origin.rstrip("/") != str(request.base_url).rstrip("/"):
            return JSONResponse({"detail": "请从系统页面操作"}, status_code=403)
    try:
        return await call_next(request)
    except Exception:
        logging.exception("未处理的请求错误 %s %s", request.method, request.url.path)
        return JSONResponse({"detail": "操作失败，请稍后重试；如持续出现，请联系管理员查看日志"}, status_code=500)


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/setup/status")
def setup_status():
    with connect() as db:
        return {"needed": db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0}


@app.post("/api/setup")
def setup(request: Request, data: dict = Body(...)):
    if not request.client or request.client.host not in {"127.0.0.1", "::1"}:
        error("请在服务器主机上完成首次管理员设置", 403)
    username = require_text(data.get("username"), "账号", 40)
    display = require_text(data.get("display_name"), "姓名", 40)
    password = str(data.get("password") or "")
    if len(password) < 10:
        error("密码至少10位")
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
            error("管理员已设置", 409)
        db.execute("INSERT INTO users(username,display_name,password_hash,role,created_at) VALUES(?,?,?,?,?)",
                   (username, display, password_hash(password), "admin", now()))
    return {"ok": True}


@app.post("/api/login")
def login(data: dict = Body(...)):
    with connect() as db:
        user = get_one(db, "SELECT * FROM users WHERE username=? AND active=1", (str(data.get("username") or ""),))
        if not user or not verify_password(str(data.get("password") or ""), user["password_hash"]):
            error("账号或密码错误", 401)
        token = secrets.token_urlsafe(32)
        expiry = (datetime.now().astimezone() + timedelta(days=7)).isoformat(timespec="seconds")
        db.execute("INSERT INTO sessions(token_hash,user_id,expires_at) VALUES(?,?,?)",
                   (hashlib.sha256(token.encode()).hexdigest(), user["id"], expiry))
    response = JSONResponse({"id": user["id"], "display_name": user["display_name"], "role": user["role"]})
    response.set_cookie("elevator_session", token, httponly=True, samesite="strict", max_age=604800)
    return response


@app.post("/api/logout")
def logout(request: Request, user=Depends(actor)):
    token = request.cookies.get("elevator_session", "")
    with connect() as db:
        db.execute("DELETE FROM sessions WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),))
    response = JSONResponse({"ok": True})
    response.delete_cookie("elevator_session")
    return response


@app.get("/api/me")
def me(user=Depends(actor)):
    return user


@app.get("/api/users")
def list_users(user=Depends(admin)):
    with connect() as db:
        return rows(db.execute("SELECT id,username,display_name,role,active,created_at FROM users ORDER BY id"))


@app.post("/api/users")
def create_user(data: dict = Body(...), user=Depends(admin)):
    username = require_text(data.get("username"), "账号", 40)
    display = require_text(data.get("display_name"), "姓名", 40)
    password = str(data.get("password") or "")
    if len(password) < 10:
        error("密码至少10位")
    role = data.get("role", "staff")
    if not isinstance(role, str) or role not in {"admin", "staff"}:
        error("角色不正确")
    with connect() as db:
        try:
            cursor = db.execute("INSERT INTO users(username,display_name,password_hash,role,created_at) VALUES(?,?,?,?,?)",
                                (username, display, password_hash(password), role, now()))
        except sqlite3.IntegrityError:
            error("账号已存在", 409)
        audit(db, user["id"], "新增", "用户", cursor.lastrowid, after={"username": username, "role": role})
    return {"id": cursor.lastrowid}


@app.put("/api/users/{user_id}")
def edit_user(user_id: int, data: dict = Body(...), user=Depends(admin)):
    with connect() as db:
        before = get_one(db, "SELECT id,username,display_name,role,active FROM users WHERE id=?", (user_id,))
        if not before:
            error("找不到用户", 404)
        display = require_text(data.get("display_name", before["display_name"]), "姓名", 40)
        role = data.get("role", before["role"])
        active = flag(data.get("active", before["active"]), "账号状态")
        if not isinstance(role, str) or role not in {"admin", "staff"}:
            error("角色不正确")
        if user_id == user["id"] and (role != "admin" or not active):
            error("不能取消自己的管理员权限")
        if before["role"] == "admin" and before["active"] and (role != "admin" or not active):
            active_admins = db.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND active=1").fetchone()[0]
            if active_admins <= 1:
                error("必须保留至少一位启用的管理员")
        password = data.get("password")
        if password and len(str(password)) < 10:
            error("新密码至少10位")
        db.execute("UPDATE users SET display_name=?,role=?,active=? WHERE id=?", (display, role, active, user_id))
        if not active:
            db.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
        if password:
            db.execute("UPDATE users SET password_hash=? WHERE id=?", (password_hash(str(password)), user_id))
            db.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
        audit(db, user["id"], "修改", "用户", user_id, before=before,
              after={"display_name": display, "role": role, "active": active, "password_changed": bool(password)})
    return {"ok": True}


@app.get("/api/buildings")
def buildings(user=Depends(actor)):
    with connect() as db:
        return rows(db.execute("""SELECT b.id,b.name,COUNT(DISTINCT e.id) elevator_count FROM buildings b
          LEFT JOIN units u ON u.building_id=b.id AND u.deleted_at IS NULL
          LEFT JOIN elevators e ON e.unit_id=u.id AND e.deleted_at IS NULL
          WHERE b.deleted_at IS NULL GROUP BY b.id ORDER BY b.name"""))


@app.post("/api/buildings")
def add_building(data: dict = Body(...), user=Depends(admin)):
    name = require_text(data.get("name"), "楼栋名称", 40)
    with connect() as db:
        try:
            cursor = db.execute("INSERT INTO buildings(name) VALUES(?)", (name,))
        except sqlite3.IntegrityError:
            error("楼栋名称已存在（含已删除资料，可在系统管理中恢复）", 409)
        audit(db, user["id"], "新增", "楼栋", cursor.lastrowid, after={"name": name})
    return {"id": cursor.lastrowid}


@app.put("/api/buildings/{building_id}")
def edit_building(building_id: int, data: dict = Body(...), user=Depends(admin)):
    name = require_text(data.get("name"), "楼栋名称", 40)
    with connect() as db:
        before = must_exist(db, "buildings", building_id)
        if not before:
            error("找不到楼栋", 404)
        try:
            db.execute("UPDATE buildings SET name=? WHERE id=?", (name, building_id))
        except sqlite3.IntegrityError:
            error("楼栋名称已存在", 409)
        audit(db, user["id"], "修改", "楼栋", building_id, before=before, after={"name": name})
    return {"ok": True}


@app.delete("/api/buildings/{building_id}")
def delete_building(building_id: int, user=Depends(admin)):
    with connect() as db:
        before = must_exist(db, "buildings", building_id)
        if not before:
            error("找不到楼栋", 404)
        if db.execute("SELECT 1 FROM units WHERE building_id=? AND deleted_at IS NULL", (building_id,)).fetchone():
            error("此楼栋还有单元，请先处理单元")
        db.execute("UPDATE buildings SET deleted_at=? WHERE id=?", (now(), building_id))
        audit(db, user["id"], "删除", "楼栋", building_id, before=before)
    return {"ok": True}


@app.get("/api/units")
def units(building_id: Optional[int] = None, user=Depends(actor)):
    with connect() as db:
        query = """SELECT u.id,u.name,u.building_id,b.name building_name,
          COUNT(e.id) elevator_count FROM units u JOIN buildings b ON b.id=u.building_id
          LEFT JOIN elevators e ON e.unit_id=u.id AND e.deleted_at IS NULL
          WHERE u.deleted_at IS NULL AND b.deleted_at IS NULL"""
        args = []
        if building_id:
            query += " AND u.building_id=?"
            args.append(building_id)
        return rows(db.execute(query + " GROUP BY u.id ORDER BY b.name,u.name", args))


@app.post("/api/units")
def add_unit(data: dict = Body(...), user=Depends(admin)):
    name = require_text(data.get("name"), "单元名称", 40)
    with connect() as db:
        if not must_exist(db, "buildings", positive_int(data.get("building_id"), "楼栋", 1)):
            error("请选择已有楼栋")
        try:
            cursor = db.execute("INSERT INTO units(building_id,name) VALUES(?,?)", (data["building_id"], name))
        except sqlite3.IntegrityError:
            error("该楼栋已有同名单元（含已删除资料，可在系统管理中恢复）", 409)
        audit(db, user["id"], "新增", "单元", cursor.lastrowid, after={"name": name})
    return {"id": cursor.lastrowid}


@app.put("/api/units/{unit_id}")
def edit_unit(unit_id: int, data: dict = Body(...), user=Depends(admin)):
    name = require_text(data.get("name"), "单元名称", 40)
    with connect() as db:
        before = must_exist(db, "units", unit_id)
        if not before:
            error("找不到单元", 404)
        try:
            db.execute("UPDATE units SET name=? WHERE id=?", (name, unit_id))
        except sqlite3.IntegrityError:
            error("该楼栋已有同名单元（含已删除资料，可在系统管理中恢复）", 409)
        audit(db, user["id"], "修改", "单元", unit_id, before=before, after={"name": name})
    return {"ok": True}


@app.delete("/api/units/{unit_id}")
def delete_unit(unit_id: int, user=Depends(admin)):
    with connect() as db:
        before = must_exist(db, "units", unit_id)
        if not before:
            error("找不到单元", 404)
        if db.execute("SELECT 1 FROM elevators WHERE unit_id=? AND deleted_at IS NULL", (unit_id,)).fetchone():
            error("此单元还有电梯，请先处理电梯")
        db.execute("UPDATE units SET deleted_at=? WHERE id=?", (now(), unit_id))
        audit(db, user["id"], "删除", "单元", unit_id, before=before)
    return {"ok": True}


ELEVATOR_FIELDS = ("internal_number", "equipment_number", "brand", "model", "manufactured_on", "started_on",
                   "maintenance_company", "maintenance_contact", "maintenance_phone", "inspection_on", "maintenance_due_on", "status", "notes")


def elevator_values(data):
    values = {field: optional_text(data.get(field), 500) for field in ELEVATOR_FIELDS}
    for field, label in (("manufactured_on", "出厂日期"), ("started_on", "投用日期"),
                         ("inspection_on", "下次年检日期"), ("maintenance_due_on", "下次维保日期")):
        values[field] = day(values[field], label)
    values["status"] = values["status"] or "正常"
    if values["status"] not in STATUSES:
        error("电梯状态不正确")
    return values


def resolve_unit(db, data, user):
    if 'building_name' not in data and 'unit_name' not in data:
        unit_id = positive_int(data.get('unit_id'), '单元', 1)
        unit = must_exist(db, 'units', unit_id)
        if not unit or not must_exist(db, 'buildings', unit['building_id']):
            error('请选择已有单元')
        return unit_id
    building = require_text(data.get('building_name'), '楼栋', 40)
    unit = require_text(data.get('unit_name'), '单元', 40)
    for table, name, parent in [('buildings', building, None), ('units', unit, 'building_id')]:
        condition = 'name=?' + (' AND building_id=?' if parent else '')
        args = (name, building_id) if parent else (name,)
        existing = get_one(db, f'SELECT * FROM {table} WHERE {condition}', args)
        if existing:
            if existing['deleted_at']:
                error(f'{name}已删除，请先在系统管理中恢复', 409)
            item_id = existing['id']
        else:
            statement = 'INSERT INTO units(name,building_id) VALUES(?,?)' if parent else 'INSERT INTO buildings(name) VALUES(?)'
            item_id = db.execute(statement, args).lastrowid
            audit(db, user['id'], '新增', '单元' if parent else '楼栋', item_id, after={'name':name})
        if not parent:
            building_id = item_id
    return item_id


def insert_elevator(db, data, user):
    name = require_text(data.get('name'), '电梯名称', 50)
    values = elevator_values(data)
    unit_id = resolve_unit(db, data, user)
    payload = {'unit_id':unit_id, 'name':name, **values}
    try:
        cursor = db.execute(f"INSERT INTO elevators({','.join(payload)}) VALUES({','.join('?' for _ in payload)})", list(payload.values()))
    except sqlite3.IntegrityError:
        error('该单元已有同名电梯（含已删除资料，可在系统管理中恢复）', 409)
    audit(db, user['id'], '新增', '电梯', cursor.lastrowid, after=payload)
    return cursor.lastrowid


@app.get('/api/elevator-archives/export')
def export_archives(template: bool = False, building_id: Optional[int] = None, unit_id: Optional[int] = None, user=Depends(actor)):
    from urllib.parse import quote
    records = [] if template else elevators(building_id, unit_id, user)
    filename = COMMUNITY + '_电梯档案' + ('导入模板' if template else '_' + date.today().strftime('%Y%m%d')) + '.xlsx'
    return Response(workbook_bytes(records), media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                    headers={'Content-Disposition': "attachment; filename*=UTF-8''" + quote(filename)})


@app.post('/api/elevator-archives/import')
async def import_archives(file: UploadFile = File(...), dry_run: bool = True, user=Depends(admin)):
    if Path(file.filename or '').suffix.lower() != '.xlsx':
        error('请选择.xlsx格式的电梯档案模板')
    raw = await file.read(5 * 1024 * 1024 + 1)
    await file.close()
    if not raw or len(raw) > 5 * 1024 * 1024:
        error('表格需大于0且不超过5MB')
    try:
        records = read_records(raw)
    except Exception as exc:
        error(str(exc) if isinstance(exc, ValueError) else '无法读取表格，请使用下载的.xlsx模板')
    errors, preview, seen = [], [], set()
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        for number, data in records:
            try:
                name = require_text(data.get('name'), '电梯名称', 50)
                elevator_values(data)
                key = (require_text(data.get('building_name'), '楼栋', 40), require_text(data.get('unit_name'), '单元', 40), name)
                if key in seen:
                    error('表格内重复出现同一部电梯')
                seen.add(key)
                unit_id = resolve_unit(db, data, user)
                existing = get_one(db, 'SELECT id,deleted_at FROM elevators WHERE unit_id=? AND name=?', (unit_id,name))
                if existing and existing['deleted_at']:
                    error('该电梯已删除，请先在系统管理中恢复')
                action = '跳过' if existing else '新增'
                if not existing:
                    insert_elevator(db, {**data, 'unit_id':unit_id}, user)
                preview.append({'row':number,'place':' / '.join(key),'action':action})
            except HTTPException as exc:
                errors.append(f'第{number}行：{exc.detail}')
        if errors or dry_run:
            db.rollback()
        if errors:
            return {'valid':False, 'errors':errors[:20], 'error_count':len(errors), 'rows':[], 'added':0, 'skipped':0}
    return {'valid':True, 'errors':[], 'rows':preview, 'added':sum(r['action']=='新增' for r in preview),
            'skipped':sum(r['action']=='跳过' for r in preview), 'committed':not dry_run}


@app.get("/api/elevators")
def elevators(building_id: Optional[int] = None, unit_id: Optional[int] = None, user=Depends(actor)):
    with connect() as db:
        sql = """SELECT e.*,u.name unit_name,u.building_id,b.name building_name FROM elevators e
          JOIN units u ON u.id=e.unit_id JOIN buildings b ON b.id=u.building_id
          WHERE e.deleted_at IS NULL AND u.deleted_at IS NULL AND b.deleted_at IS NULL"""
        args = []
        if building_id:
            sql += " AND b.id=?"; args.append(building_id)
        if unit_id:
            sql += " AND u.id=?"; args.append(unit_id)
        items = rows(db.execute(sql + " ORDER BY b.name,u.name,e.name", args))
        for item in items:
            item["community"] = COMMUNITY
        return items


@app.post("/api/elevators")
def add_elevator(data: dict = Body(...), user=Depends(admin)):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        elevator_id = insert_elevator(db, data, user)
    return {"id": elevator_id}


@app.get("/api/elevators/{elevator_id}")
def elevator(elevator_id: int, user=Depends(actor)):
    with connect() as db:
        item = get_one(db, """SELECT e.*,u.name unit_name,u.building_id,b.name building_name FROM elevators e
          JOIN units u ON u.id=e.unit_id JOIN buildings b ON b.id=u.building_id
          WHERE e.id=? AND e.deleted_at IS NULL""", (elevator_id,))
        if not item:
            error("找不到这部电梯", 404)
        item["community"] = COMMUNITY
        item["total_cost_cents"] = db.execute("SELECT COALESCE(SUM(cost_cents),0) FROM events WHERE elevator_id=? AND deleted_at IS NULL", (elevator_id,)).fetchone()[0]
        return item


@app.put("/api/elevators/{elevator_id}")
def edit_elevator(elevator_id: int, data: dict = Body(...), user=Depends(admin)):
    values = elevator_values(data)
    values["name"] = require_text(data.get("name"), "电梯名称", 50)
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        before = must_exist(db, "elevators", elevator_id)
        if not before:
            error("找不到这部电梯", 404)
        if 'building_name' in data or 'unit_name' in data:
            values['unit_id'] = resolve_unit(db, data, user)
        try:
            db.execute(f"UPDATE elevators SET {','.join(f'{k}=?' for k in values)} WHERE id=?", (*values.values(), elevator_id))
        except sqlite3.IntegrityError:
            error("该单元已有同名电梯（含已删除资料，可在系统管理中恢复）", 409)
        audit(db, user["id"], "修改", "电梯", elevator_id, before=before, after=values)
    return {"ok": True}


@app.delete("/api/elevators/{elevator_id}")
def delete_elevator(elevator_id: int, user=Depends(admin)):
    with connect() as db:
        before = must_exist(db, "elevators", elevator_id)
        if not before:
            error("找不到这部电梯", 404)
        db.execute("UPDATE elevators SET deleted_at=? WHERE id=?", (now(), elevator_id))
        audit(db, user["id"], "删除", "电梯", elevator_id, before=before)
    return {"ok": True}


EVENT_FIELDS = ("started_at", "ended_at", "work_content", "resolution", "workers", "company", "notes",
                "fault_at", "symptom", "reported_at", "arrived_at", "restored_at", "cause", "remedy")


def event_values(data):
    typ = data.get("type")
    if not isinstance(typ, str) or typ not in TYPES:
        error("请选择工作类型")
    values = {field: optional_text(data.get(field), 5000 if field in {"work_content", "resolution", "symptom", "remedy"} else 1000) for field in EVENT_FIELDS}
    values.update(type=typ, title=require_text(data.get("title"), "标题", 120),
                  cost_auto=int(data.get("cost_yuan") in (None, "")),
                  occurred_on=day(data.get("occurred_on"), "工作日期", True),
                  cost_cents=money(data.get("cost_yuan") if data.get("cost_yuan") not in (None, "") else 0), completed=flag(data.get("completed", True), "完成情况"),
                  stopped=flag(data.get("stopped", False), "是否停梯"), recovered=flag(data.get("recovered", False), "是否恢复正常"))
    for field in ("started_at", "ended_at", "fault_at", "reported_at", "arrived_at", "restored_at"):
        if values[field]:
            try:
                datetime.fromisoformat(values[field])
            except ValueError:
                error("时间格式不正确")
    for start, end, label in (("started_at", "ended_at", "结束时间"), ("fault_at", "reported_at", "报修时间"),
                              ("reported_at", "arrived_at", "到场时间"), ("arrived_at", "restored_at", "恢复时间")):
        if values[start] and values[end]:
            try:
                if datetime.fromisoformat(values[end]) < datetime.fromisoformat(values[start]):
                    error(f"{label}不能早于前一时间")
            except TypeError:
                error("同一记录的时间格式应一致")
    return values


def part_values(part, occurred_on):
    if not isinstance(part, dict):
        error("配件内容格式不正确")
    replaced = day(part.get("replaced_on") or occurred_on, "更换日期", True)
    warranty_days = positive_int(part.get("warranty_days", 0), "质保天数")
    warranty_from = day(part.get("warranty_from") or replaced, "质保开始日期", True)
    try:
        until = (date.fromisoformat(warranty_from) + timedelta(days=warranty_days)).isoformat() if warranty_days else None
    except OverflowError:
        error("质保截止日期超出允许范围")
    return dict(name=require_text(part.get("name"), "配件名称", 100), model=optional_text(part.get("model"), 100),
                quantity=positive_int(part.get("quantity", 1), "数量", 1), unit_price_cents=money(part.get("unit_price_yuan", 0)),
                replaced_on=replaced, reason=optional_text(part.get("reason"), 1000), brand=optional_text(part.get("brand"), 100),
                warranty_days=warranty_days, warranty_from=warranty_from, warranty_until=until,
                notes=optional_text(part.get("notes"), 1000))


def event_full(db, event_id):
    item = get_one(db, """SELECT v.*, e.name elevator_name,u.name unit_name,b.name building_name
        FROM events v JOIN elevators e ON e.id=v.elevator_id JOIN units u ON u.id=e.unit_id
        JOIN buildings b ON b.id=u.building_id WHERE v.id=? AND v.deleted_at IS NULL
        AND e.deleted_at IS NULL AND u.deleted_at IS NULL AND b.deleted_at IS NULL""", (event_id,))
    if item:
        for field in ("completed", "stopped", "recovered"):
            item[field] = bool(item[field])
        item["parts"] = rows(db.execute("SELECT * FROM event_parts WHERE event_id=? ORDER BY id", (event_id,)))
        for part in item["parts"]:
            part["total_price_cents"] = part["quantity"] * part["unit_price_cents"]
        item["attachments"] = rows(db.execute("""SELECT a.*,u.display_name uploaded_name FROM attachments a
            JOIN users u ON u.id=a.uploaded_by WHERE a.event_id=? AND a.deleted_at IS NULL ORDER BY a.sort_order,a.created_at,a.id""", (event_id,)))
    return item


@app.get("/api/events")
def events(elevator_id: Optional[int] = None, limit: int = 100, offset: int = 0,
           order: str = "desc", type: str = "全部", start: Optional[str] = None, end: Optional[str] = None, user=Depends(actor)):
    start = day(start); end = day(end)
    if start and end and start > end:
        error("开始日期不能晚于结束日期")
    if type != "全部" and type not in TYPES:
        error("工作类型不正确")
    limit = max(1, min(limit, 500))
    offset = max(0, min(offset, 1_000_000))
    direction = "ASC" if order == "asc" else "DESC"
    with connect() as db:
        sql = """SELECT v.id FROM events v JOIN elevators e ON e.id=v.elevator_id
          WHERE v.deleted_at IS NULL AND e.deleted_at IS NULL"""
        args = []
        if elevator_id:
            sql += " AND v.elevator_id=?"; args.append(elevator_id)
        for clause, value in (("v.type=?", type if type != "全部" else None), ("v.occurred_on>=?", start), ("v.occurred_on<=?", end)):
            if value:
                sql += " AND " + clause; args.append(value)
        ids = [row[0] for row in db.execute(sql + f" ORDER BY v.occurred_on {direction},v.id {direction} LIMIT ? OFFSET ?", (*args, limit, offset))]
        return [event_full(db, x) for x in ids]


@app.get("/api/events/{event_id}")
def event(event_id: int, user=Depends(actor)):
    with connect() as db:
        item = event_full(db, event_id)
        if not item:
            error("找不到这条工作记录", 404)
        return item


def update_record_status(db, data, elevator_id, user, event_id):
    # A completed repair does not prove the elevator is safe to operate. Only use explicit staff input.
    status = data.get("elevator_status")
    if status in (None, ""):
        return
    if not isinstance(status, str) or status not in STATUSES:
        error("电梯状态不正确")
    before = must_exist(db, "elevators", elevator_id)
    db.execute("UPDATE elevators SET status=? WHERE id=?", (status, elevator_id))
    audit(db, user["id"], "修改", "电梯状态", elevator_id, before={"status": before["status"]},
          after={"status": status, "event_id": event_id})


@app.post("/api/events")
def add_event(data: dict = Body(...), user=Depends(actor)):
    values = event_values(data)
    parts = data.get("parts") or []
    if not isinstance(parts, list) or len(parts) > 30:
        error("配件数量不正确")
    if values["type"] == "配件更换" and not parts:
        error("配件更换记录至少需要填写一个配件")
    parsed_parts = [part_values(p, values["occurred_on"]) for p in parts]
    if sum(part["quantity"] * part["unit_price_cents"] for part in parsed_parts) > 10_000_000_000:
        error("本次配件合计不能超过一亿元")
    if data.get("cost_yuan") is None or data.get("cost_yuan") == "":
        values["cost_cents"] = sum(part["quantity"] * part["unit_price_cents"] for part in parsed_parts)
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        if not must_exist(db, "elevators", positive_int(data.get("elevator_id"), "电梯", 1)):
            error("请选择已有电梯")
        stamp = now()
        payload = {"elevator_id": data["elevator_id"], **values, "created_by": user["id"], "created_at": stamp, "updated_at": stamp}
        fields = list(payload)
        cursor = db.execute(f"INSERT INTO events({','.join(fields)}) VALUES({','.join('?' for _ in fields)})", list(payload.values()))
        for part in parsed_parts:
            fields = list(part)
            db.execute(f"INSERT INTO event_parts(event_id,{','.join(fields)}) VALUES(?,{','.join('?' for _ in fields)})",
                       [cursor.lastrowid, *part.values()])
        update_record_status(db, data, data["elevator_id"], user, cursor.lastrowid)
        audit(db, user["id"], "新增", "工作记录", cursor.lastrowid, after={**payload, "parts": parsed_parts})
    return {"id": cursor.lastrowid, "updated_at": payload["updated_at"]}


@app.put("/api/events/{event_id}")
def edit_event(event_id: int, data: dict = Body(...), user=Depends(actor)):
    values = event_values(data)
    parts = data.get("parts") or []
    if not isinstance(parts, list) or len(parts) > 30:
        error("配件数量不正确")
    if values["type"] == "配件更换" and not parts:
        error("配件更换记录至少需要填写一个配件")
    parsed_parts = [part_values(p, values["occurred_on"]) for p in parts]
    if sum(part["quantity"] * part["unit_price_cents"] for part in parsed_parts) > 10_000_000_000:
        error("本次配件合计不能超过一亿元")
    if data.get("cost_yuan") is None or data.get("cost_yuan") == "":
        values["cost_cents"] = sum(part["quantity"] * part["unit_price_cents"] for part in parsed_parts)
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        before = event_full(db, event_id)
        if not before:
            error("找不到这条工作记录", 404)
        if user["role"] != "admin" and before["created_by"] != user["id"]:
            error("只能修改自己创建的记录", 403)
        if data.get("updated_at") and data["updated_at"] != before["updated_at"]:
            error("这条记录刚被其他人修改，请重新打开后再编辑", 409)
        values["updated_at"] = now()
        db.execute(f"UPDATE events SET {','.join(f'{k}=?' for k in values)} WHERE id=?", (*values.values(), event_id))
        db.execute("DELETE FROM event_parts WHERE event_id=?", (event_id,))
        for part in parsed_parts:
            fields = list(part)
            db.execute(f"INSERT INTO event_parts(event_id,{','.join(fields)}) VALUES(?,{','.join('?' for _ in fields)})",
                       [event_id, *part.values()])
        update_record_status(db, data, before["elevator_id"], user, event_id)
        audit(db, user["id"], "修改", "工作记录", event_id, before=before, after={**values, "parts": parsed_parts})
    return {"ok": True, "updated_at": values["updated_at"]}


@app.delete("/api/events/{event_id}")
def delete_event(event_id: int, user=Depends(admin)):
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        before = event_full(db, event_id)
        if not before:
            error("找不到这条工作记录", 404)
        db.execute("UPDATE events SET deleted_at=? WHERE id=?", (now(), event_id))
        audit(db, user["id"], "删除", "工作记录", event_id, before=before)
    return {"ok": True}


@app.get("/api/elevators/{elevator_id}/parts")
def part_history(elevator_id: int, user=Depends(actor)):
    with connect() as db:
        if not must_exist(db, "elevators", elevator_id):
            error("找不到这部电梯", 404)
        items = rows(db.execute("""SELECT p.*,v.title FROM event_parts p JOIN events v ON v.id=p.event_id
            WHERE v.elevator_id=? AND v.deleted_at IS NULL ORDER BY p.name,p.replaced_on DESC,p.id DESC""", (elevator_id,)))
    previous = {}
    for item in sorted(items, key=lambda x: (x["name"].strip().casefold(), x["replaced_on"], x["id"])):
        key = item["name"].strip().casefold()
        item["days_since_previous"] = (date.fromisoformat(item["replaced_on"]) - date.fromisoformat(previous[key])).days if key in previous else None
        previous[key] = item["replaced_on"]
        item["total_price_cents"] = item["quantity"] * item["unit_price_cents"]
    return items


def validate_file(raw, ext):
    if ext in {".jpg", ".jpeg", ".png", ".webp"}:
        try:
            image = Image.open(io.BytesIO(raw))
            if image.width * image.height > 80_000_000:
                error("图片像素过大，请上传不超过8000万像素的原图")
            image.verify()
        except HTTPException:
            raise
        except Exception:
            error("图片文件无效")
    elif ext == ".pdf" and not raw.startswith(b"%PDF-"):
        error("PDF文件无效")
    elif ext in {".docx", ".xlsx"}:
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                required = "word/document.xml" if ext == ".docx" else "xl/workbook.xml"
                if required not in archive.namelist():
                    error("Office文件无效")
        except zipfile.BadZipFile:
            error("Office文件无效")
    elif ext in {".doc", ".xls"} and not raw.startswith(bytes.fromhex("D0CF11E0A1B11AE1")):
        error("Office文件无效")


@app.post("/api/events/{event_id}/attachments")
async def upload(event_id: int, file: UploadFile = File(...), category: str = Form("其他"), user=Depends(actor)):
    if category not in CATEGORIES:
        error("附件分类不正确")
    original = (file.filename or "").replace("\\", "/").split("/")[-1].strip()
    if not original or len(original) > 200 or any(ord(char) < 32 for char in original):
        error("文件名无效")
    ext = Path(original).suffix.lower()
    if ext not in EXTENSIONS:
        error("文件格式不支持")
    raw = await file.read(MAX_UPLOAD + 1)
    if not raw or len(raw) > MAX_UPLOAD:
        error("文件不能为空，且不能超过20 MB")
    validate_file(raw, ext)
    file_id = uuid.uuid4().hex
    relative = Path("photos" if ext in {".jpg", ".jpeg", ".png", ".webp"} else "attachments") / f"{file_id}{ext}"
    target = STORAGE / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    with connect() as db:
        event = event_full(db, event_id)
        if not event:
            error("找不到这条工作记录", 404)
        if user["role"] != "admin" and event["created_by"] != user["id"]:
            error("只能为自己创建的记录上传附件", 403)
        target.write_bytes(raw)
        try:
            order = db.execute("SELECT COALESCE(MAX(sort_order),0)+1 FROM attachments WHERE event_id=?", (event_id,)).fetchone()[0]
            db.execute("""INSERT INTO attachments(id,event_id,elevator_id,original_name,relative_path,category,mime_type,size,uploaded_by,created_at,sort_order)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)""", (file_id, event_id, event["elevator_id"], original, relative.as_posix(), category,
                                            mimetypes.guess_type(original)[0] or "application/octet-stream", len(raw), user["id"], now(), order))
            audit(db, user["id"], "新增", "附件", file_id, after={"original_name": original, "event_id": event_id})
        except Exception:
            target.unlink(missing_ok=True)
            raise
    return {"id": file_id, "original_name": original}


@app.put("/api/events/{event_id}/attachment-order")
def order_attachments(event_id: int, data: dict = Body(...), user=Depends(actor)):
    ids = data.get("ids")
    if not isinstance(ids, list) or not all(isinstance(item, str) for item in ids) or len(ids) != len(set(ids)):
        error("附件顺序不正确，请刷新后重试")
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        event = event_full(db, event_id)
        if not event:
            error("找不到这条工作记录", 404)
        if user["role"] != "admin" and event["created_by"] != user["id"]:
            error("只能调整自己创建记录的附件顺序", 403)
        before = [item["id"] for item in event["attachments"]]
        if set(ids) != set(before):
            error("附件已变化，请刷新记录后重新调整", 409)
        db.executemany("UPDATE attachments SET sort_order=? WHERE id=? AND event_id=?",
                       [(index, item, event_id) for index, item in enumerate(ids, 1)])
        audit(db, user["id"], "修改", "附件顺序", event_id, before={"ids": before}, after={"ids": ids})
    return {"ok": True}


@app.get("/api/attachments/{file_id}")
def attachment(file_id: str, download: bool = False, user=Depends(actor)):
    with connect() as db:
        item = get_one(db, """SELECT a.* FROM attachments a JOIN events v ON v.id=a.event_id
            JOIN elevators e ON e.id=v.elevator_id WHERE a.id=? AND a.deleted_at IS NULL
            AND v.deleted_at IS NULL AND e.deleted_at IS NULL""", (file_id,))
    if not item:
        error("找不到附件", 404)
    target = (STORAGE / item["relative_path"]).resolve()
    if not target.is_relative_to(STORAGE.resolve()) or not target.is_file():
        error("附件文件不存在", 404)
    return FileResponse(target, media_type=item["mime_type"], filename=item["original_name"],
                        content_disposition_type="attachment" if download else "inline",
                        headers={"X-Content-Type-Options": "nosniff"})


@app.delete("/api/attachments/{file_id}")
def delete_attachment(file_id: str, user=Depends(actor)):
    with connect() as db:
        item = get_one(db, """SELECT a.* FROM attachments a JOIN events v ON v.id=a.event_id
            JOIN elevators e ON e.id=v.elevator_id WHERE a.id=? AND a.deleted_at IS NULL
            AND v.deleted_at IS NULL AND e.deleted_at IS NULL""", (file_id,))
        if not item:
            error("找不到附件", 404)
        if user["role"] != "admin" and item["uploaded_by"] != user["id"]:
            error("只能删除自己上传的附件", 403)
        db.execute("UPDATE attachments SET deleted_at=? WHERE id=?", (now(), file_id))
        audit(db, user["id"], "删除", "附件", file_id, before=item)
    return {"ok": True}


@app.get("/api/search")
def search(q: str = "", user=Depends(actor)):
    if len(q) > 200 or len(q.split()) > 10:
        error("搜索内容请控制在200字、10个关键词以内")
    terms = q.strip().split()
    if not terms:
        return {"elevators": [], "events": [], "truncated": False}
    base = """FROM elevators e JOIN units u ON u.id=e.unit_id JOIN buildings b ON b.id=u.building_id
        LEFT JOIN events v ON v.elevator_id=e.id AND v.deleted_at IS NULL
        WHERE e.deleted_at IS NULL AND u.deleted_at IS NULL AND b.deleted_at IS NULL"""
    fields = ("b.name", "u.name", "e.name", "e.internal_number", "e.equipment_number", "e.maintenance_company",
              "v.title", "v.work_content", "v.symptom", "v.resolution", "v.occurred_on", "v.company",
              "v.cause", "v.remedy", "v.notes", "v.workers")
    args = []
    for term in terms:
        like = "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        base += " AND (" + " OR ".join(field + " LIKE ? ESCAPE '\\'" for field in fields)
        base += " OR EXISTS (SELECT 1 FROM event_parts p WHERE p.event_id=v.id AND p.name LIKE ? ESCAPE '\\'))"
        args.extend([like] * (len(fields) + 1))
    with connect() as db:
        elevators_found = rows(db.execute("SELECT DISTINCT e.id,e.name,e.status,b.name building_name,u.name unit_name " + base + " ORDER BY b.name,u.name,e.name LIMIT 101", args))
        ids = [row[0] for row in db.execute("SELECT DISTINCT v.id " + base + " AND v.id IS NOT NULL ORDER BY v.occurred_on DESC,v.id DESC LIMIT 101", args)]
        return {"elevators": elevators_found[:100], "events": [event_full(db, x) for x in ids[:100]],
                "truncated": len(elevators_found) > 100 or len(ids) > 100}


def reminders_data(db):
    today = date.today()
    result = []
    for item in rows(db.execute("""SELECT p.id part_id,p.name,p.warranty_until,e.id elevator_id,e.name elevator_name,u.name unit_name,b.name building_name
        FROM event_parts p JOIN events v ON v.id=p.event_id JOIN elevators e ON e.id=v.elevator_id
        JOIN units u ON u.id=e.unit_id JOIN buildings b ON b.id=u.building_id
        WHERE p.warranty_until IS NOT NULL AND v.deleted_at IS NULL AND e.deleted_at IS NULL""")):
        days = (date.fromisoformat(item["warranty_until"]) - today).days
        if days <= 30:
            result.append({**item, "kind": "配件质保", "due_on": item["warranty_until"], "days_left": days,
                           "level": "已到期" if days < 0 else "7天内到期" if days <= 7 else "30天内到期"})
    for item in rows(db.execute("""SELECT e.id elevator_id,e.name elevator_name,u.name unit_name,b.name building_name,
         e.maintenance_due_on,e.inspection_on FROM elevators e JOIN units u ON u.id=e.unit_id
         JOIN buildings b ON b.id=u.building_id WHERE e.deleted_at IS NULL""")):
        for field, kind in (("maintenance_due_on", "维保"), ("inspection_on", "年检")):
            if item[field]:
                days = (date.fromisoformat(item[field]) - today).days
                if days <= 30:
                    result.append({**item, "kind": kind, "due_on": item[field], "days_left": days,
                                   "level": "已逾期" if days < 0 else "即将到期"})
    return sorted(result, key=lambda x: (x["days_left"], x["building_name"], x["unit_name"]))


@app.get("/api/reminders")
def reminders(user=Depends(actor)):
    with connect() as db:
        return reminders_data(db)


@app.get("/api/dashboard")
def dashboard(user=Depends(actor)):
    with connect() as db:
        stats = dict(db.execute("""SELECT COUNT(*) total, SUM(status='正常') normal,
          SUM(status='故障') fault, SUM(status='维修中') repairing FROM elevators WHERE deleted_at IS NULL""").fetchone())
        month = date.today().strftime("%Y-%m")
        stats["monthly_repairs"] = db.execute("SELECT COUNT(*) FROM events v JOIN elevators e ON e.id=v.elevator_id WHERE v.type='维修' AND v.occurred_on LIKE ? AND v.deleted_at IS NULL AND e.deleted_at IS NULL", (month + "%",)).fetchone()[0]
        stats["monthly_parts"] = db.execute("""SELECT COALESCE(SUM(p.quantity),0) FROM event_parts p JOIN events v ON v.id=p.event_id JOIN elevators e ON e.id=v.elevator_id
          WHERE v.occurred_on LIKE ? AND v.deleted_at IS NULL AND e.deleted_at IS NULL""", (month + "%",)).fetchone()[0]
        recent = rows(db.execute("""SELECT v.id,v.elevator_id,v.type,v.title,v.occurred_on,v.completed,e.name elevator_name,u.name unit_name,b.name building_name
           FROM events v JOIN elevators e ON e.id=v.elevator_id JOIN units u ON u.id=e.unit_id JOIN buildings b ON b.id=u.building_id
           WHERE v.deleted_at IS NULL AND e.deleted_at IS NULL ORDER BY v.occurred_on DESC,v.id DESC LIMIT 15"""))
        return {"stats": stats, "reminders": reminders_data(db), "recent": recent}


@app.get("/api/costs")
def costs(building_id: Optional[int] = None, unit_id: Optional[int] = None, elevator_id: Optional[int] = None,
          start: Optional[str] = None, end: Optional[str] = None, type: str = "全部", user=Depends(actor)):
    if type != "全部" and type not in TYPES:
        error("工作类型不正确")
    start = day(start); end = day(end)
    if start and end and start > end:
        error("开始日期不能晚于结束日期")
    sql = """SELECT COALESCE(SUM(v.cost_cents),0) cost_cents,COUNT(*) record_count FROM events v
      JOIN elevators e ON e.id=v.elevator_id JOIN units u ON u.id=e.unit_id WHERE v.deleted_at IS NULL AND e.deleted_at IS NULL"""
    args = []
    for clause, value in (("v.type=?", type if type != "全部" else None), ("u.building_id=?", building_id), ("u.id=?", unit_id), ("v.elevator_id=?", elevator_id),
                          ("v.occurred_on>=?", start), ("v.occurred_on<=?", end)):
        if value:
            sql += " AND " + clause; args.append(value)
    with connect() as db:
        return dict(db.execute(sql, args).fetchone())


def network_info(request):
    with connect() as db:
        saved = get_one(db, "SELECT value FROM system_settings WHERE key='lan_base_url'")
    port = request.url.port or (443 if request.url.scheme == 'https' else 80)
    suffix = f':{port}' if port != (443 if request.url.scheme == 'https' else 80) else ''
    candidates = [f'{request.url.scheme}://{address}{suffix}' for address in addresses()]
    try:
        current = validate_base(str(request.base_url))
    except ValueError:
        current = ''
    if current and current not in candidates:
        candidates.insert(0, current)
    configured = saved['value'] if saved else ''
    base = configured or current or (candidates[0] if len(candidates) == 1 else '')
    return {'configured_url': configured, 'base_url': base, 'candidates': candidates,
            'source': 'saved' if configured else 'current' if current else 'detected' if base else 'missing'}


@app.get("/api/network")
def get_network(request: Request, user=Depends(actor)):
    return network_info(request)


@app.put("/api/network")
def set_network(request: Request, data: dict = Body(...), user=Depends(admin)):
    try:
        base = validate_base(data.get('base_url'))
    except ValueError as exc:
        error(str(exc))
    with connect() as db:
        before = get_one(db, "SELECT value FROM system_settings WHERE key='lan_base_url'")
        db.execute("INSERT INTO system_settings(key,value) VALUES('lan_base_url',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (base,))
        audit(db, user['id'], '修改', '局域网访问地址', 'lan_base_url', before, {'value': base})
    return network_info(request)


def elevator_qr_info(elevator_id, request):
    with connect() as db:
        if not must_exist(db, "elevators", elevator_id):
            error("找不到这部电梯", 404)
    info = network_info(request)
    return {**info, 'url': info['base_url'] + f'/elevators/{elevator_id}' if info['base_url'] else ''}


@app.get("/api/elevators/{elevator_id}/qr-info")
def qr_info(elevator_id: int, request: Request, user=Depends(actor)):
    return elevator_qr_info(elevator_id, request)


@app.get("/api/elevators/{elevator_id}/qr")
def qr(elevator_id: int, request: Request, user=Depends(actor)):
    info = elevator_qr_info(elevator_id, request)
    if not info['url']:
        error('尚未确定局域网地址，请管理员在系统管理中设置后再下载二维码', 409)
    image = qrcode.make(info['url'])
    output = io.BytesIO(); image.save(output, format="PNG")
    return Response(output.getvalue(), media_type="image/png", headers={"Cache-Control": "no-store"})


TRASH = {"buildings": ("楼栋", "name"), "units": ("单元", "name"), "elevators": ("电梯", "name"),
         "events": ("工作记录", "title"), "attachments": ("附件", "original_name")}


@app.get("/api/trash")
def trash_list(user=Depends(admin)):
    items = []
    with connect() as db:
        for table, (label, name) in TRASH.items():
            for row in rows(db.execute(f"SELECT id,{name} name,deleted_at FROM {table} WHERE deleted_at IS NOT NULL ORDER BY deleted_at DESC LIMIT 200")):
                items.append({**row, "kind": table, "label": label})
    return sorted(items, key=lambda x: x["deleted_at"], reverse=True)[:200]


@app.post("/api/trash/{kind}/{record_id}/restore")
def restore(kind: str, record_id: str, user=Depends(admin)):
    if kind not in TRASH:
        error("资料类型不正确")
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        item = get_one(db, f"SELECT * FROM {kind} WHERE id=? AND deleted_at IS NOT NULL", (record_id,))
        if not item:
            error("找不到已删除资料", 404)
        parent = {"units": ("buildings", "building_id"), "elevators": ("units", "unit_id"),
                  "events": ("elevators", "elevator_id"), "attachments": ("events", "event_id")}.get(kind)
        if parent and not must_exist(db, parent[0], item[parent[1]]):
            error("请先恢复所属楼栋、单元、电梯或工作记录")
        if kind == "attachments":
            if not event_full(db, item["event_id"]):
                error("请先恢复所属电梯和工作记录")
            path = (STORAGE / item["relative_path"]).resolve()
            if not path.is_relative_to(STORAGE.resolve()) or not path.is_file():
                error("原始附件文件缺失，请从备份恢复")
        db.execute(f"UPDATE {kind} SET deleted_at=NULL WHERE id=?", (record_id,))
        audit(db, user["id"], "恢复", TRASH[kind][0], record_id, before=item)
    return {"ok": True}


@app.get("/api/audit")
def audit_list(user=Depends(admin)):
    with connect() as db:
        return rows(db.execute("""SELECT a.id,a.action,a.target,a.target_id,a.created_at,u.display_name
          FROM audit_logs a LEFT JOIN users u ON u.id=a.user_id ORDER BY a.id DESC LIMIT 200"""))


@app.post("/api/backup")
def backup(user=Depends(admin)):
    try:
        path = create_backup()
    except ValueError as exc:
        error(str(exc))
    with connect() as db:
        audit(db, user["id"], "备份", "系统", path.name)
    return {"filename": path.name, "download": f"/api/backups/{path.name}"}


@app.get("/api/backups/{filename}")
def get_backup(filename: str, user=Depends(admin)):
    if not filename.startswith("backup_") or Path(filename).name != filename or not filename.endswith(".zip"):
        error("备份文件名无效")
    path = BACKUPS / filename
    if not path.is_file():
        error("找不到备份文件", 404)
    return FileResponse(path, filename=filename)


def prepare_export(scope, building_id, unit_id, elevator_id, start, end, type, photos, directory, package, user):
    if not isinstance(scope, str) or scope not in {"all", "building", "unit", "elevator"}:
        error("导出范围不正确")
    if not isinstance(type, str) or (type != "全部" and type not in TYPES):
        error("工作类型不正确")
    scope_id = {"building": building_id, "unit": unit_id, "elevator": elevator_id}.get(scope)
    if scope != "all":
        positive_int(scope_id, "导出范围", 1)
    start = day(start); end = day(end)
    if start and end and start > end:
        error("开始日期不能晚于结束日期")
    try:
        path, download_name = make_export(scope, building_id, unit_id, elevator_id, start, end, type, photos, directory, package)
    except ValueError as exc:
        error(str(exc))
    except Exception:
        logging.exception("Word生成失败")
        error("生成档案失败，请联系管理员查看日志", 500)
    with connect() as db:
        audit(db, user["id"], "导出", "工作档案", download_name)
    return path, download_name


def export_draft_row(db, draft_id, user):
    item = get_one(db, '''SELECT d.*,u.display_name created_by_name FROM export_drafts d
        JOIN users u ON u.id=d.created_by WHERE d.id=?''', (draft_id,))
    if not item:
        error('找不到这份工作文稿', 404)
    if user['role'] != 'admin' and item['created_by'] != user['id']:
        error('只能查看和修改自己创建的文稿', 403)
    return item


def draft_blocks(value, source):
    if not isinstance(value, list) or len(value) > 5000:
        error('文稿最多包含5000个内容块，请缩小来源范围')
    pictures = {attachment['id'] for _, _, attachment in source_attachments(source)
                if attachment['relative_path'].startswith('photos/')}
    blocks, ids, used_pictures = [], set(), set()
    for block in value:
        if not isinstance(block, dict):
            error('文稿内容格式不正确')
        block_id, kind = block.get('id'), block.get('type')
        if not isinstance(block_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', block_id) or block_id in ids:
            error('文稿内容块编号无效或重复')
        ids.add(block_id)
        if kind in ('heading', 'paragraph'):
            blocks.append({'id': block_id, 'type': kind,
                           'text': optional_text(block.get('text'), 300 if kind == 'heading' else 10000)})
        elif kind == 'image':
            attachment_id = block.get('attachment_id')
            if not isinstance(attachment_id, str) or attachment_id not in pictures:
                error('只能插入这份文稿来源记录中的照片')
            if attachment_id in used_pictures:
                error('同一张照片不能重复插入正文')
            used_pictures.add(attachment_id)
            blocks.append({'id': block_id, 'type': kind, 'attachment_id': attachment_id,
                           'caption': optional_text(block.get('caption'), 500)})
        else:
            error('文稿内容类型不正确')
    return blocks


@app.post('/api/export-drafts')
def create_export_draft(data: dict = Body(...), user=Depends(actor)):
    scope, typ = data.get('scope', 'all'), data.get('type', '全部')
    if not isinstance(scope, str) or scope not in {'all', 'building', 'unit', 'elevator'}:
        error('导出范围不正确')
    if not isinstance(typ, str) or (typ != '全部' and typ not in TYPES):
        error('工作类型不正确')
    filters = {'scope': scope, 'type': typ, 'start': day(data.get('start')), 'end': day(data.get('end')),
               'photos': bool(flag(data.get('photos', True), '包含照片')),
               'directory': bool(flag(data.get('directory', True), '附件目录')),
               'package': bool(flag(data.get('package', False), '完整档案包'))}
    for key in ('building_id', 'unit_id', 'elevator_id'):
        filters[key] = positive_int(data[key], '导出范围', 1) if data.get(key) is not None else None
    if scope != 'all' and not filters[scope + '_id']:
        error('请先选择导出范围')
    if filters['start'] and filters['end'] and filters['start'] > filters['end']:
        error('开始日期不能晚于结束日期')
    try:
        source = get_data(scope, filters['building_id'], filters['unit_id'], filters['elevator_id'],
                          filters['start'], filters['end'], typ)
    except ValueError as exc:
        error(str(exc))
    blocks = draft_blocks(initial_blocks(source, filters['photos']), source)
    metadata = draft_metadata(source, filters)
    title = f"{metadata['scope_label']} {metadata['period_label']}电梯工作记录档案"
    stamp = now()
    with connect() as db:
        cursor = db.execute('''INSERT INTO export_drafts(created_by,title,filters_json,source_json,blocks_json,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?)''', (user['id'], title, json.dumps(filters, ensure_ascii=False),
            json.dumps(source, ensure_ascii=False), json.dumps(blocks, ensure_ascii=False), stamp, stamp))
        draft_id = cursor.lastrowid
        audit(db, user['id'], '新增', '工作文稿', draft_id, after={'title': title, 'filters': filters, 'revision': 1})
        item = export_draft_row(db, draft_id, user)
    return draft_detail(item)


@app.get('/api/export-drafts')
def list_export_drafts(user=Depends(actor)):
    with connect() as db:
        sql = '''SELECT d.id,d.created_by,u.display_name created_by_name,d.title,d.revision,d.created_at,d.updated_at
                 FROM export_drafts d JOIN users u ON u.id=d.created_by'''
        args = ()
        if user['role'] != 'admin':
            sql += ' WHERE d.created_by=?'; args = (user['id'],)
        return rows(db.execute(sql + ' ORDER BY d.updated_at DESC,d.id DESC', args))


@app.get('/api/export-drafts/{draft_id}')
def get_export_draft(draft_id: int, user=Depends(actor)):
    with connect() as db:
        item = export_draft_row(db, draft_id, user)
    return draft_detail(item)


@app.put('/api/export-drafts/{draft_id}')
def save_export_draft(draft_id: int, data: dict = Body(...), user=Depends(actor)):
    title = require_text(data.get('title'), '文稿标题', 200)
    revision = positive_int(data.get('revision'), '文稿版本', 1)
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        before = export_draft_row(db, draft_id, user)
        blocks = draft_blocks(data.get('blocks'), json.loads(before['source_json']))
        cursor = db.execute('''UPDATE export_drafts SET title=?,blocks_json=?,revision=revision+1,updated_at=?,
            docx_name=NULL,zip_name=NULL WHERE id=? AND revision=?''',
            (title, json.dumps(blocks, ensure_ascii=False), now(), draft_id, revision))
        if cursor.rowcount != 1:
            error('这份文稿刚被其他人修改，当前编辑内容已保留；请先重新打开最新版本', 409)
        audit(db, user['id'], '修改', '工作文稿', draft_id,
              before={'title': before['title'], 'revision': before['revision']}, after={'title': title, 'revision': revision + 1})
        item = export_draft_row(db, draft_id, user)
    return draft_detail(item)


@app.get('/api/export-drafts/{draft_id}/images/{attachment_id}')
def export_draft_image(draft_id: int, attachment_id: str, user=Depends(actor)):
    with connect() as db:
        item = export_draft_row(db, draft_id, user)
    source = json.loads(item['source_json'])
    selected = next(((e, v, a) for e, v, a in source_attachments(source) if a['id'] == attachment_id
                     and a['relative_path'].startswith('photos/')), None)
    if not selected:
        error('找不到来源照片', 404)
    elevator, event, attachment = selected
    status, _ = source_status([{**elevator, 'events': [{**event, 'attachments': [attachment]}]}])
    if status[attachment_id]:
        error(status[attachment_id], 404)
    return FileResponse(STORAGE / attachment['relative_path'], media_type=attachment['mime_type'],
                        headers={'X-Content-Type-Options': 'nosniff'})


@app.post('/api/export-drafts/{draft_id}/prepare')
def prepare_export_draft(draft_id: int, data: dict = Body(...), user=Depends(actor)):
    revision = positive_int(data.get('revision'), '文稿版本', 1)
    package = bool(flag(data.get('package', False), '完整档案包'))
    directory = bool(flag(data.get('directory', True), '附件目录'))
    with connect() as db:
        item = export_draft_row(db, draft_id, user)
    if revision != item['revision']:
        error('文稿版本已变化，请先保存或重新打开最新版本', 409)
    try:
        docx_path, zip_path, filename = make_draft_export(item, package, directory)
    except ValueError as exc:
        error(str(exc))
    except Exception:
        logging.exception('工作文稿生成失败')
        error('生成文稿失败，请联系管理员查看日志', 500)
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        cursor = db.execute('''UPDATE export_drafts SET docx_name=?,zip_name=? WHERE id=? AND revision=?''',
            (docx_path.name, zip_path.name if zip_path else None, draft_id, revision))
        if cursor.rowcount != 1:
            docx_path.unlink(missing_ok=True)
            if zip_path:
                zip_path.unlink(missing_ok=True)
            error('生成期间文稿已修改，请重新生成', 409)
        audit(db, user['id'], '导出', '工作文稿', draft_id, after={'filename': filename, 'revision': revision})
    path = zip_path or docx_path
    return {'download': f'/api/export-drafts/{draft_id}/download/{path.name}', 'filename': filename}


@app.get('/api/export-drafts/{draft_id}/download/{stored_name}')
def download_export_draft(draft_id: int, stored_name: str, user=Depends(actor)):
    with connect() as db:
        item = export_draft_row(db, draft_id, user)
    if Path(stored_name).name != stored_name or stored_name not in (item['docx_name'], item['zip_name']):
        error('找不到这份文稿导出文件，请重新生成', 404)
    path = EXPORTS / stored_name
    if not path.is_file():
        error('文稿导出文件不存在，请重新生成', 404)
    return FileResponse(path, filename=stored_name.split('_', 1)[1], media_type='application/zip' if path.suffix == '.zip' else
                        'application/vnd.openxmlformats-officedocument.wordprocessingml.document')


@app.get("/api/export")
def export(scope: str = "all", building_id: Optional[int] = None, unit_id: Optional[int] = None,
           elevator_id: Optional[int] = None, start: Optional[str] = None, end: Optional[str] = None,
           type: str = "全部", photos: bool = True, directory: bool = True,
           package: bool = False, user=Depends(actor)):
    path, download_name = prepare_export(scope, building_id, unit_id, elevator_id, start, end,
                                         type, photos, directory, package, user)
    return FileResponse(path, filename=download_name, media_type="application/zip" if package else
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document")


@app.post("/api/export/prepare")
def export_prepare(data: dict = Body(...), user=Depends(actor)):
    path, download_name = prepare_export(data.get("scope", "all"), data.get("building_id"),
        data.get("unit_id"), data.get("elevator_id"), data.get("start"), data.get("end"),
        data.get("type", "全部"), bool(flag(data.get("photos", True), "包含照片")), bool(flag(data.get("directory", True), "附件目录")),
        bool(flag(data.get("package", False), "完整档案包")), user)
    return {"download": f"/api/exports/{path.name}", "filename": download_name}


@app.get("/api/exports/{stored_name}")
def export_download(stored_name: str, user=Depends(actor)):
    if not re.fullmatch(r"[0-9a-f]{12}_.+\.(docx|zip)", stored_name) or Path(stored_name).name != stored_name:
        error("档案文件名无效")
    path = EXPORTS / stored_name
    if not path.is_file():
        error("找不到档案文件", 404)
    download_name = stored_name.split("_", 1)[1]
    return FileResponse(path, filename=download_name, media_type="application/zip" if path.suffix == ".zip" else
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document")


DIST = ROOT / "frontend" / "dist"
if DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")


@app.get("/{path:path}")
def frontend(path: str):
    if path.startswith("api/"):
        error("页面不存在", 404)
    index = DIST / "index.html"
    if index.exists():
        return FileResponse(index)
    return HTMLResponse("前端尚未构建。请运行 npm run build。", status_code=503)
