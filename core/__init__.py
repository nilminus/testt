app = None

import pip
import argparse
import pkg_resources
import sys

def check_requirements():
    requirements_path = 'requirements.txt'
    requirements = open(requirements_path, 'r').read().split('\n')
    try:
        pkg_resources.require(requirements)
    except:
        print("[!] Requirements missing. Try 'pip install -r requirements.txt'")
        sys.exit(1)
