from core import check_requirements

# Verify all pkg requirments are installed
check_requirements()

import argparse
import sys
import os
import traceback
import pymysql
import socket
from core import logging

try:
    from core import database
except (pymysql.Error, pymysql.Warning) as e:
    logging.error("Failed to load databse module! Verify settings in 'core/config.py'")
    logging.print(str(e))
    sys.exit(1)

from flask import Flask
from flask_login import LoginManager
from threading import Thread

from core import config
from core import routing
from core.install import prompt_for_install
from core import icmp

if __name__ == '__main__':

    parser = argparse.ArgumentParser(description="Beaconing C2 server for Throwback agent")
    parser.add_argument('-d', '--delete', help="Delete throwback database", action='store_true')
    parser.add_argument('-u', '--update-skeleton', help="Update database skeleton (commands, return codes, oeprating systems)", 
                        action='store_true')
    args = parser.parse_args(sys.argv[1:])

    if args.delete:
        if input("Are you sure you want to delete ALL Throwback data? (Y/n): ").lower() != 'n':
            database.delete_database()
            logging.success('Database deleted.')
            sys.exit(1)

    if not database.check_database_exists():
        prompt_for_install()

    logging.print('''                                  
 _____ _                 _           _   
|_   _| |_ ___ ___ _ _ _| |_ ___ ___| |_ 
  | | |   |  _| . | | | | . | .'|  _| '_|
  |_| |_|_|_| |___|_____|___|__,|___|_,_|
                                         ws
    ''')

    if args.update_skeleton:
        database.update_skeleton()
        logging.success("Updated database skeleton")

    config.print_all()

    icmp_interface = "0.0.0.0"
    if os.name == 'nt':
        icmp_interface = input ('  Interface IP for the ICMP server: ')
        print('')

    icmp_listener = Thread(target = icmp.StartICMPServer, args = (icmp_interface, ))
    icmp_listener.start()

    app = Flask(__name__, template_folder="core/templates", static_folder="core/static")
    app.config.update( SECRET_KEY = config.get_setting('encryption_key') , DEBUG = True)
    routing.setup_routes(app)

    logging.success("Starting HTTP Server")

    app.run('0.0.0.0', 80, threaded=True, use_reloader=False)
