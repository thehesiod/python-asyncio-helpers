#!/usr/bin/env python
from setuptools import setup
import re
import os


_packages = {
    'asyncio_helpers': 'asyncio_helpers',
}


def read_version():
    regexp = re.compile(r"^__version__\W*=\W*'([\d.abrc]+)'")
    init_py = os.path.join(os.path.dirname(__file__),
                           'asyncio_helpers', '__init__.py')
    with open(init_py) as f:
        for line in f:
            match = regexp.match(line)
            if match is not None:
                return match.group(1)
        else:
            raise RuntimeError('Cannot find version in '
                               'asyncio_helpers/__init__.py')


setup(
    name="asyncio-helpers",
    version=read_version(),
    description='Asyncio Helpers',
    classifiers=[
        'Intended Audience :: Developers',
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6',
    ],
    author='Alexander Mohr',
    author_email='thehesiod@gmail.com',
    url='https://github.com/thehesiod/python-asyncio-helpers',
    package_dir=_packages,
    packages=list(_packages.keys()),
    install_requires=[
        'moto',
        'wrapt',
        'netifaces',
        'aiohttp'
    ],

    dependency_links=[
        # until release with https://github.com/spulec/moto/pull/1611 + https://github.com/spulec/moto/commit/b5bdf6693c1ed615571b1099766c411600d3db10 is available
        'git+https://github.com/spulec/moto.git@80929292584ee78affc07643d16fae6bb31b4014#egg=moto[server]',
    ]
)
