"""Verify and sync a complete skill without deleting user-owned files."""
import argparse
import hashlib
import json
import shutil
import sys
import importlib
from pathlib import Path
from html_contract import atomic_json

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {'assets/reading-theme.js', 'assets/reading-insights.js'}
REQUIRED = ['SKILL.md','scripts/generate_reading_html.py','scripts/collect_html_materials.py',
    'scripts/build_reading_html.py','scripts/html_contract.py','scripts/embed_fonts.py',
    'assets/reading-template.html','assets/reading-app.js','assets/reading-share-art.js',
    'assets/reading-app.css','assets/reading-art.css',
    'assets/lieflat-LICENSE.txt','assets/yearbook-art/hero-book.png','assets/yearbook-art/reading.png',
    'assets/yearbook-art/rhythm.png','assets/fonts/NotoSerifSC.ttf.zlib','assets/fonts/NotoSansSC.ttf.zlib',
    'assets/fonts/OFL-Serif.txt','assets/fonts/OFL-Sans.txt',
    'scripts/serve_ebook.py','scripts/ebook_document.py','scripts/ebook_runner.py','scripts/ebook_pipeline.py',
    'scripts/ebook_verification.py','scripts/ebook_agent.py','scripts/ebook_agent_bridge.py','scripts/ebook_title.py','scripts/ebook_reading.py',
    'assets/ebook-app.js','assets/ebook-app.css','assets/ebook-section.html',
    'references/distillation-method.md','references/title-research.md','references/book-review-writing.md','references/book-reading-writing.md','requirements-ebook.txt',
    'third_party/cangjie/UPSTREAM.json','third_party/cangjie/LICENSE']


def check_resources(root=ROOT):
    missing=[name for name in REQUIRED if not (Path(root)/name).is_file()]
    if missing:
        raise ValueError('Skill安装缺件：'+', '.join(missing)+'；请完整重新安装Skill目录')


def check_dependencies(root=ROOT):
    vendor=Path(root)/'.vendor'
    if vendor.exists():sys.path.insert(0,str(vendor))
    try:
        pillow=importlib.import_module('PIL')
    except ImportError:
        raise ValueError('缺少图片校验依赖Pillow；助手应在Skill目录按requirements.txt补齐依赖后再采集') from None
    try:
        importlib.import_module('fontTools');importlib.import_module('brotli')
        subsetting=True
    except ImportError:
        subsetting=False
    return {'pillow':pillow.__version__,'font_subsetting':subsetting}


def manifest(root=ROOT):
    root=Path(root)
    files=[]
    for p in sorted(root.rglob('*')):
        relative=p.relative_to(root)
        if relative.as_posix() in EXCLUDED or not p.is_file() or any(x in relative.parts for x in ('__pycache__','.vendor','revisions','output','private','.ebook-workbench','.cache','.history','.diagnostics')) or p.name in ('release-manifest.json','validation-report.json'):
            continue
        kind='text-lf' if p.suffix.lower() in {'.py','.js','.cjs','.svg','.xml','.html','.css','.md','.txt','.json','.yaml','.yml','.template'} else 'binary'
        files.append({'path':relative.as_posix(),'sha256':file_hash(p,kind),'hash_kind':kind,'bytes':p.stat().st_size})
    return {'version':'2026.10.25','files':files}


def file_hash(path,kind='binary'):
    content=Path(path).read_bytes()
    if kind=='text-lf':content=content.replace(b'\r\n',b'\n')
    return hashlib.sha256(content).hexdigest()


def verify(root=ROOT):
    root=Path(root);check_resources(root)
    expected=json.loads((root/'release-manifest.json').read_text('utf-8'))
    for item in expected['files']:
        path=(root/item['path']).resolve()
        if not path.is_relative_to(root.resolve()) or not path.is_file():
            raise ValueError('发布文件缺失或路径无效：'+item['path'])
        if file_hash(path,item.get('hash_kind','binary'))!=item['sha256']:
            raise ValueError('发布文件版本不匹配：'+item['path'])
    return expected


def install(destination, with_local_dependencies=False):
    expected=verify();destination=Path(destination).resolve()
    if destination==ROOT.resolve() or destination.is_relative_to(ROOT.resolve()):
        raise ValueError('安装目录应在源码目录之外')
    destination.mkdir(parents=True,exist_ok=True)
    for item in expected['files']:
        target=destination/item['path'];target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(ROOT/item['path'],target)
    shutil.copy2(ROOT/'release-manifest.json',destination/'release-manifest.json')
    if with_local_dependencies:
        if not (ROOT/'.vendor').is_dir():raise ValueError('源码目录没有本地依赖，请按requirements.txt安装')
        shutil.copytree(ROOT/'.vendor',destination/'.vendor',dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    verify(destination)
    return {'installed':str(destination),'version':expected['version'],'files':len(expected['files'])}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--write-manifest',action='store_true');parser.add_argument('--install',type=Path)
    parser.add_argument('--with-local-dependencies',action='store_true',help='仅本机同一Python环境：同步已安装的.vendor依赖')
    args=parser.parse_args()
    if args.write_manifest:atomic_json(ROOT/'release-manifest.json',manifest())
    print(json.dumps(install(args.install,args.with_local_dependencies) if args.install else {'version':verify()['version'],'status':'valid','dependencies':check_dependencies()},ensure_ascii=False))
