# Copyright (c) 2026 rui-rc. See LICENSE and NOTICE.
"""Fetch official reference assets only when the user has rights to use them."""
import hashlib
import json
from pathlib import Path
from urllib.request import Request, urlopen


def fetch(requirements=None):
    root=Path(requirements or Path(__file__).resolve().parents[1]/'requirements').resolve()
    manifest=json.loads((root/'brand-assets.json').read_text(encoding='utf-8'))
    folder=root/'assets';folder.mkdir(exist_ok=True)
    for item in manifest['assets']:
        target=(root/item['path']).resolve()
        if not target.is_relative_to(folder.resolve()):raise ValueError('Unexpected asset path')
        if target.exists():
            if hashlib.sha256(target.read_bytes()).hexdigest()==item['sha256']:
                print('Already present:',target.name);continue
            raise ValueError('Existing asset differs; preserve it and investigate: '+target.name)
        req=Request(item['source_url'],headers={'User-Agent':'Mozilla/5.0','Referer':'https://mp.weixin.qq.com/'})
        with urlopen(req,timeout=30) as response:data=response.read(10*1024*1024+1)
        if len(data)>10*1024*1024 or hashlib.sha256(data).hexdigest()!=item['sha256']:
            raise ValueError('Source asset failed integrity check: '+target.name)
        target.write_bytes(data)
        print('Verified:',target.name)

if __name__=='__main__':fetch()
