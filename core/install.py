import sys
import getpass
import hashlib
import random
import string

from core import database
from .config import Config
from .config import get_setting

def prompt_for_install():

    if input('\n[+] Would you like to start the install? (Y/n): ').lower() == 'n':
        sys.exit(1)

    database.create_database()
    print('\n[+] Created database\n')

    # Add login user
    username = input("[+] Username for the first user? ({0}): ".format(Config.first_user))
    if not username:
        username = Config.first_user

    password = ""
    while not password:
        password = input("[+] Password: ")
        
    password = hashlib.sha1(password.encode()).hexdigest()

    database.cursor.execute('''
    INSERT INTO `users` (`username`, `password`, `lastlogin`) VALUES
    (%s, %s, %s);
    ''', (username, password, '0'))

    # Setup callback parameters
    encryption_key = input("[+] Encryption key for RC4? [leave blank to auto-generate]: ")
    if not encryption_key:
        encryption_key = ''.join(random.choice(string.ascii_letters + string.digits) for _ in range(32))


    callback_path = input("[+] URL endpoint for callbacks [TTP]? ({0}): ".format(Config.callback_page))
    if not callback_path:
        callback_path = Config.callback_page
    if callback_path[0] != '/':
        callback_path = '/' + callback_path

    post_variable = input("[+] POST variable for requests [TTP]? ({0}): ".format(Config.post_variable))
    if not post_variable:
        post_variable = Config.post_variable

    get_variable = input("[+] GET variable for requests [TTP]? ({0}): ".format(Config.get_variable))
    if not get_variable:
        get_variable = Config.get_variable

    meta_tag_name = input("[+] HTTP meta tag name for requests [TTP]? ({0}): ".format(Config.meta_tag_name))
    if not meta_tag_name:
        meta_tag_name = Config.meta_tag_name

    database.cursor.execute('''
    INSERT INTO `config` (`name`, `value`) VALUES
    ('callback_path', %s),
    ('encryption_key', %s),
    ('post_variable', %s),
    ('get_variable', %s),
    ('meta_tag_name', %s)
    ''', (callback_path, encryption_key, post_variable, get_variable, meta_tag_name))   

    print('[+] Saved configuration')

    print('\n[+] Install is complete')



  