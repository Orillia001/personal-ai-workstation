"""Narrow, revision-checked access to DeskBox's existing todo stores."""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import threading
import uuid
import time
from datetime import datetime
from ctypes import wintypes

_LOCK = threading.Lock()
OWNER_REPLY_LIMIT = 16 * 1024 * 1024


def pipe_request(widget, payload, scope='7F3A9B2E'):
    """Ask the current-user DeskBox owner to apply a change on its UI thread."""
    import msvcrt
    name = rf'\\.\pipe\DeskBox.Workstation.{scope}.{widget}'
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.WaitNamedPipeW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD]
    kernel.PeekNamedPipe.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                                   ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    raw = (json.dumps(payload, ensure_ascii=False) + '\n').encode('utf-8')
    if len(raw) > 60000:
        raise ValueError('事项内容过长')
    stream = None
    connect_deadline = time.monotonic() + 1.5
    while time.monotonic() < connect_deadline:
        if kernel.WaitNamedPipeW(name, 200):
            try:
                stream = open(name, 'r+b', buffering=0)
                break
            except OSError as exc:
                if getattr(exc, 'winerror', None) not in (2, 231):
                    raise
        time.sleep(.02)
    if stream is None:
        raise ValueError('DeskBox 热更新补丁尚未连接；请启动补丁版本后重试')
    with stream:
        stream.write(raw)
        response = bytearray()
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            available = wintypes.DWORD()
            handle = msvcrt.get_osfhandle(stream.fileno())
            if not kernel.PeekNamedPipe(handle, None, 0, None, ctypes.byref(available), None):
                break
            if available.value:
                response.extend(stream.read(min(available.value, 65536, OWNER_REPLY_LIMIT + 1 - len(response))))
                if len(response) > OWNER_REPLY_LIMIT:
                    raise ValueError('DeskBox 列表应答过大，请缩小列表后重试')
                if b'\n' in response:
                    data = json.loads(response.split(b'\n', 1)[0])
                    if data.get('error'):
                        raise ValueError(data['error'])
                    return data
            time.sleep(.03)
    raise ValueError('未能确认 DeskBox 保存结果，请先刷新列表核对，再决定是否重试')


def deskbox_running():
    # Enumerate processes without opening their memory or guessing from windows.
    if os.name != 'nt':
        raise ValueError('无法核实 DeskBox 进程，暂不允许写入')
    class Entry(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('usage', wintypes.DWORD),
                    ('pid', wintypes.DWORD), ('heap', ctypes.c_size_t),
                    ('module', wintypes.DWORD), ('threads', wintypes.DWORD),
                    ('parent', wintypes.DWORD), ('priority', wintypes.LONG),
                    ('flags', wintypes.DWORD), ('exe', wintypes.WCHAR * 260)]
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
    kernel.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateToolhelp32Snapshot(2, 0)
    if handle == ctypes.c_void_p(-1).value:
        raise ValueError('无法核实 DeskBox 进程，暂不允许写入')
    try:
        entry = Entry()
        entry.size = ctypes.sizeof(entry)
        found = kernel.Process32FirstW(handle, ctypes.byref(entry))
        if not found:
            raise ValueError('无法读取进程列表，暂不允许写入')
        while found:
            if entry.exe.lower() == 'deskbox.exe':
                return True
            found = kernel.Process32NextW(handle, ctypes.byref(entry))
        if ctypes.get_last_error() != 18:  # ERROR_NO_MORE_FILES
            raise ValueError('进程检查不完整，暂不允许写入')
        return False
    finally:
        kernel.CloseHandle(handle)


class DeskBoxFiles:
    def __init__(self, station_root, widgets_root=None, running=deskbox_running):
        self.station = Path(station_root)
        self.widgets = Path(widgets_root) if widgets_root else Path(os.environ['LOCALAPPDATA']) / 'DeskBox/data/widgets'
        self.running = running

    def path(self, widget):
        if not isinstance(widget, str):
            raise ValueError('DeskBox 列表标识无效')
        try:
            if str(uuid.UUID(widget)) != widget:
                raise ValueError()
        except (ValueError, AttributeError):
            raise ValueError('DeskBox 列表标识无效') from None
        base = self.widgets.resolve()
        path = self.widgets / widget / 'todo.json'
        if path.resolve() != base / widget / 'todo.json':
            raise ValueError('不允许跳转到其他目录')
        return path

    def read(self, widget):
        path = self.path(widget)
        raw = path.read_bytes()
        if len(raw) > 8 * 1024 * 1024:
            raise ValueError('DeskBox 待办文件过大')
        data = json.loads(raw.decode('utf-8-sig'))
        if not isinstance(data, dict) or data.get('version') != 3 or not isinstance(data.get('items'), list):
            raise ValueError('暂不支持此 DeskBox 数据格式')
        ids = set()
        for item in data['items']:
            if not isinstance(item, dict) or not isinstance(item.get('id'), str) or item['id'] in ids:
                raise ValueError('DeskBox 事项标识无效或重复')
            ids.add(item['id'])
        return path, raw, data

    def load(self):
        stores = []
        running = self.running()
        for path in sorted(self.widgets.glob('*/todo.json')):
            _, raw, data = self.read(path.parent.name)
            live = False
            owner = None
            live_error = ''
            if running and os.name == 'nt':
                try:
                    owner = pipe_request(path.parent.name, {'action': 'ping'})
                    live = owner.get('ready') is True
                except (ValueError, OSError) as exc:
                    live_error = str(exc)
            stores.append({'widget': path.parent.name, 'revision': owner['revision'] if live else hashlib.sha256(raw).hexdigest(), 'live': live, 'live_error': live_error,
                           'items': owner['items'] if live else [dict(id=i['id'], title=i.get('text', ''), due=i.get('dueDate'),
                                          done=i.get('isCompleted', False), recurring=bool(i.get('recurrence')))
                                     for i in data['items'] if not i.get('isDeleted')]})
        return {'stores': stores, 'running': running}

    def write(self, payload):
        with _LOCK:
            if self.running():
                path, raw, _ = self.read(payload.get('widget', ''))
                if payload.get('revision') != hashlib.sha256(raw).hexdigest():
                    raise ValueError('DeskBox 内容已变化，请刷新后重新核对草稿')
                backup = self.station / 'Backups/deskbox-file-link' / uuid.uuid4().hex
                backup.mkdir(parents=True)
                (backup / 'todo.json').write_bytes(raw)
                (backup / 'manifest.json').write_text(json.dumps({'source': str(path), 'sha256': hashlib.sha256(raw).hexdigest()}), encoding='utf-8')
                if payload.get('action') == 'import':
                    (backup / 'legacy-plan.json').write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
                result = pipe_request(payload['widget'], payload)
                return {**self.load(), 'saved': result.get('saved') is True, 'live_saved': True, 'backup': str(backup)}
            path, raw, data = self.read(payload.get('widget', ''))
            if payload.get('revision') != hashlib.sha256(raw).hexdigest():
                raise ValueError('DeskBox 内容已变化，请刷新列表后重新编辑；未覆盖新内容')
            action = payload.get('action')
            now = datetime.now().astimezone().isoformat()
            if action == 'add':
                item = {'id': uuid.uuid4().hex, 'text': '', 'isCompleted': False,
                        'createdAt': now, 'sortOrder': len(data['items']), 'isDeleted': False}
                data['items'].append(item)
            else:
                item = next((i for i in data['items'] if i['id'] == payload.get('id') and not i.get('isDeleted')), None)
                if item is None:
                    raise ValueError('事项已不存在，请刷新列表')
            if action in ('add', 'edit'):
                title = payload.get('title')
                if not isinstance(title, str) or not title.strip() or len(title) > 500:
                    raise ValueError('请输入 1–500 字的事项标题')
                due = payload.get('due') or None
                if due:
                    if not isinstance(due, str) or len(due) > 40:
                        raise ValueError('计划时间无效')
                    due = datetime.fromisoformat(due).astimezone().isoformat()
                if item.get('recurrence') and due != item.get('dueDate'):
                    raise ValueError('重复事项的时间请在 DeskBox 中修改')
                item.update(text=title.strip(), dueDate=due)
            elif action == 'complete':
                if item.get('recurrence'):
                    raise ValueError('重复事项请在 DeskBox 中完成，以正确生成下一次事项')
                if type(payload.get('done')) is not bool:
                    raise ValueError('完成状态无效')
                item.update(isCompleted=payload['done'], completedAt=now if payload['done'] else None)
            elif action == 'delete':
                item['isDeleted'] = True
            else:
                raise ValueError('不支持的 DeskBox 操作')
            item['updatedAt'] = now
            backup = self.station / 'Backups/deskbox-file-link' / uuid.uuid4().hex
            backup.mkdir(parents=True)
            shutil.copy2(path, backup / 'todo.json')
            (backup / 'manifest.json').write_text(json.dumps({'source': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'time': now}), encoding='utf-8')
            encoded = json.dumps(data, ensure_ascii=False, indent=2).encode('utf-8')
            fd, temp = tempfile.mkstemp(prefix='.workstation-', suffix='.tmp', dir=path.parent)
            try:
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(encoded)
                    stream.flush()
                    os.fsync(stream.fileno())
                if self.running() or path.read_bytes() != raw:
                    raise ValueError('DeskBox 已启动或文件刚有变化，本次未写入，请退出后重试')
                os.replace(temp, path)
            finally:
                Path(temp).unlink(missing_ok=True)
            return {'saved': True, 'backup': str(backup), **self.load()}


def dispatch(root, payload):
    files = DeskBoxFiles(root)
    return files.load() if payload.get('action') == 'list' else files.write(payload)
