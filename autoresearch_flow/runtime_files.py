"""Bounded no-symlink reads across an untrusted worker output tree."""
import os
from pathlib import Path
import stat

from .common import _require


def read_tail(path, *, root, limit=65536):
    path, root = Path(path).absolute(), Path(root).absolute()
    _require(path.is_relative_to(root), 'OUTPUT_PATH', '读取不能越过本轨输出根')
    parts = path.relative_to(root).parts
    _require(parts and '..' not in parts, 'OUTPUT_PATH', '输出相对路径无效')
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for name in parts[:-1]:
            next_dir = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = next_dir
        descriptor = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        with os.fdopen(descriptor, 'rb') as stream:
            info = os.fstat(stream.fileno())
            _require(stat.S_ISREG(info.st_mode), 'OUTPUT_PATH', '输出读取须为普通文件')
            stream.seek(max(0, info.st_size-limit))
            return stream.read(limit).decode('utf-8', errors='replace')
    finally:
        os.close(directory)
