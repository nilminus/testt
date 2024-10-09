from core import logging

class Config:
    instance_id_length = 10
    
    # Database
    db = 'throwback'
    db_host = 'localhost'
    db_user = 'root'
    db_pass = 'throwbackftw'

    # Default variables for the install
    first_user = 'admin'
    callback_page = "/orders"
    post_variable = 'orderinfo'
    get_variable = 'session'
    meta_tag_name = 'key_material'


def print_all():
    from core import database # Late import to avoic cyclics

    database.cursor.execute("SELECT * FROM `config`")

    logging.success("Current config:")

    for row in database.cursor.fetchall():
        logging.print("\t'{0}': {1}".format(*row))

    logging.print('\n')

def get_setting(name):
    from core import database # Late import to avoid cyclics

    database.cursor.execute("SELECT `value` FROM `config` WHERE `name`=%s", (name))

    if database.cursor.rowcount == 1:
        return database.cursor.fetchone()[0]

    print("[!] Failed to find config setting '{0}'".format(name))
    
    return None
